"""Worklist rules, ranking, replay helpers (pure pandas) and the API against the seeded DB (skipped if unreachable)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from ml.worklist import AGREED, CALLBACK, REMOVED, WorklistConfig, overdue_candidates, rank_candidates

AS_OF = pd.Timestamp("2026-09-20")
FAC = "fac-1"


def _tables(patients: list[dict]) -> dict[str, pd.DataFrame]:
    """Build minimal tables from per-patient specs.

    spec keys: pid, scheduled (days before AS_OF), last_bp (days before scheduled; None = never), sys, dia,
    call (result_type or None), call_days_ago, remove_reason, has_phone, status
    """
    P, A, B, C = [], [], [], []
    for i, s in enumerate(patients):
        pid = s["pid"]
        sched = AS_OF - pd.Timedelta(days=s.get("scheduled", 30))
        P.append({"patient_id": pid, "status": s.get("status", "active"), "assigned_facility_id": FAC,
                  "has_phone": s.get("has_phone", True), "reminder_consent": "granted"})
        A.append({"appointment_id": f"a-{pid}", "patient_id": pid, "facility_id": FAC, "scheduled_date": sched, "status": "scheduled",
                  "booked_at": sched - pd.Timedelta(days=30), "device_updated_at": sched - pd.Timedelta(days=30)})
        if s.get("last_bp", 30) is not None:
            B.append({"patient_id": pid, "systolic": s.get("sys", 130), "diastolic": s.get("dia", 80),
                      "recorded_at": sched - pd.Timedelta(days=s.get("last_bp", 30))})
        if s.get("call"):
            C.append({"patient_id": pid, "appointment_id": f"a-{pid}", "result_type": s["call"], "remove_reason": s.get("remove_reason"),
                      "device_created_at": AS_OF - pd.Timedelta(days=s.get("call_days_ago", 3))})
    cols_c = ["patient_id", "appointment_id", "result_type", "remove_reason", "device_created_at"]
    return {"patients": pd.DataFrame(P), "appointments": pd.DataFrame(A),
            "blood_pressures": pd.DataFrame(B) if B else pd.DataFrame(columns=["patient_id", "systolic", "diastolic", "recorded_at"]),
            "call_results": pd.DataFrame(C, columns=cols_c)}


def test_eligibility_rules_follow_program_practice():
    t = _tables([
        {"pid": "plain"},
        {"pid": "agreed_recent", "call": AGREED, "call_days_ago": 5},
        {"pid": "agreed_old", "call": AGREED, "call_days_ago": 20},
        {"pid": "callback_wait", "call": CALLBACK, "call_days_ago": 2},
        {"pid": "callback_due", "call": CALLBACK, "call_days_ago": 9},
        {"pid": "removed", "call": REMOVED, "remove_reason": "moved"},
        {"pid": "ltfu", "scheduled": 300, "last_bp": 100},  # last visit 400 days ago
        {"pid": "visited_since", "scheduled": 30, "last_bp": -5},  # BP after scheduled date -> not overdue
        {"pid": "dead", "status": "dead"},
        {"pid": "not_yet_due", "scheduled": -3},
    ])
    c = overdue_candidates(t, AS_OF, WorklistConfig()).set_index("patient_id")
    assert "visited_since" not in c.index and "dead" not in c.index and "not_yet_due" not in c.index
    assert c.loc["plain", "eligible"] and c.loc["agreed_old", "eligible"] and c.loc["callback_due", "eligible"]
    assert not c.loc["agreed_recent", "eligible"] and c.loc["agreed_recent", "ineligible_reason"] == "agreed to visit recently"
    assert not c.loc["callback_wait", "eligible"] and c.loc["callback_wait", "ineligible_reason"] == "callback not yet due"
    assert not c.loc["removed", "eligible"] and c.loc["removed", "ineligible_reason"] == "removed from overdue list"
    assert not c.loc["ltfu", "eligible"] and not c.loc["ltfu", "under_care"]
    assert c.loc["callback_due", "callback_due"]
    assert c.loc["plain", "days_overdue"] == 30


def test_as_of_hides_the_future():
    """An appointment marked visited *after* as_of must still look scheduled at as_of."""
    t = _tables([{"pid": "p"}])
    t["appointments"].loc[0, "status"] = "visited"
    t["appointments"].loc[0, "device_updated_at"] = AS_OF + pd.Timedelta(days=2)
    c = overdue_candidates(t, AS_OF, WorklistConfig())
    assert list(c.patient_id) == ["p"]
    # and a BP recorded after as_of is invisible
    t["blood_pressures"] = pd.concat([t["blood_pressures"], pd.DataFrame([{"patient_id": "p", "systolic": 120, "diastolic": 80,
                                                                            "recorded_at": AS_OF + pd.Timedelta(days=1)}])])
    c2 = overdue_candidates(t, AS_OF, WorklistConfig())
    assert list(c2.patient_id) == ["p"]


def _cands(n=40, seed=0):
    rng = np.random.default_rng(seed)
    specs = [{"pid": f"p{i}", "scheduled": int(rng.integers(5, 120)), "sys": int(rng.choice([120, 150])), "has_phone": bool(rng.random() < 0.8)}
             for i in range(n)]
    c = overdue_candidates(_tables(specs), AS_OF, WorklistConfig())
    c["p_missed"] = rng.random(len(c))
    c["band"] = "medium"; c["basis"] = "personal"; c["group_size"] = 0; c["reasons"] = [[] for _ in range(len(c))]
    return c


def test_ranking_respects_capacity_phone_first_and_protected_slots():
    c = _cands()
    cfg = WorklistConfig(capacity=10, protected_share=0.3)
    r = rank_candidates(c, cfg)
    sel = r[r.selected]
    assert len(sel) == 10
    assert sel.has_phone.all(), "callable patients are ranked before home visits while any remain"
    assert sel.uncontrolled.sum() >= 3, "at least ceil(0.3*10) uncontrolled protected"
    assert sel.protected_slot.sum() == 3
    assert list(sel["rank"]) == list(range(1, 11))
    # the non-protected picks are the highest-risk remaining callable patients
    not_prot = sel[~sel.protected_slot]
    others = r[~r.selected & r.has_phone]
    assert not_prot.priority.min() >= others.priority.max()
    assert set(sel.suggested_action) <= {"call", "call_back"}
    assert set(r[~r.has_phone].suggested_action) == {"home_visit"}


def test_strategies_rank_differently_and_are_reproducible():
    c = _cands()
    risk = rank_candidates(c, WorklistConfig(capacity=8, rank_by="risk"))
    dov = rank_candidates(c, WorklistConfig(capacity=8, rank_by="days_overdue"))
    rnd1 = rank_candidates(c, WorklistConfig(capacity=8, rank_by="random", seed=1))
    rnd2 = rank_candidates(c, WorklistConfig(capacity=8, rank_by="random", seed=1))
    assert set(risk[risk.selected].patient_id) != set(dov[dov.selected].patient_id)
    assert list(rnd1.patient_id) == list(rnd2.patient_id)
    d = dov[dov.selected & ~dov.protected_slot]
    assert d.days_overdue.is_monotonic_decreasing
    with pytest.raises(ValueError):
        rank_candidates(c, WorklistConfig(rank_by="alphabetical"))


def test_worklist_output_is_identity_free(tmp_path):
    from ml.features import load_tables_from_csv
    from ml.train import load_artifact
    from ml.worklist import build_worklist
    from app.settings import REPO_ROOT

    t = load_tables_from_csv(REPO_ROOT / "data" / "synth" / "sample")
    fac = t["appointments"].facility_id.iloc[0]
    wl = build_worklist(t, pd.Timestamp("2026-09-25"), load_artifact(), WorklistConfig(capacity=5), facility_id=fac)
    forbidden = {"full_name", "phone_number", "number", "street_address", "village_or_colony", "date_of_birth", "region", "gender", "age"}
    assert not (forbidden & set(wl.columns))
    sel = wl[wl.selected]
    assert (sel.list_type == "overdue").sum() <= 5 and (sel.list_type == "pre_visit").sum() <= WorklistConfig().pre_visit_slots
    assert sel.reasons.apply(lambda r: isinstance(r, list) and any("overdue" in x or "visit in" in x for x in r)).all()


def test_return_functions_make_calls_matter_more_for_hard_patients():
    import sys
    from app.settings import REPO_ROOT
    sys.path.insert(0, str(REPO_ROOT))
    from data.synth.generate import p_return_after_call, p_return_no_call

    easy, hard = -1.5, 1.5
    assert p_return_no_call(easy) > p_return_no_call(hard)
    assert p_return_after_call(easy) > p_return_after_call(hard)
    assert (p_return_after_call(hard) - p_return_no_call(hard)) > (p_return_after_call(easy) - p_return_no_call(easy))
    assert abs(p_return_after_call(0.0) - 0.65) < 1e-9 and abs(p_return_no_call(0.0) - 0.50) < 1e-9


# ----------------------------------------------------------------------------- database-backed


def _db_ok() -> bool:
    try:
        from app.db import engine
        with engine.connect() as c:
            return c.execute(text("SELECT count(*) FROM appointments")).scalar() > 0
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_ok(), reason="needs seeded database")
TEST_DAY = date(2026, 9, 22)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def facility_id():
    from app.db import engine
    with engine.connect() as c:
        return str(c.execute(text("SELECT id FROM facilities ORDER BY id LIMIT 1")).scalar())


@pytest.fixture(autouse=True, scope="module")
def _clean_test_day():
    if not _db_ok():
        yield; return
    from app.db import engine
    with engine.begin() as c:
        c.execute(text("DELETE FROM worklist_items WHERE list_date = :d"), {"d": TEST_DAY})
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM worklist_items WHERE list_date = :d"), {"d": TEST_DAY})


@needs_db
def test_get_worklist_builds_on_demand_and_is_identity_free(client, facility_id):
    r = client.get("/worklist", params={"facility_id": facility_id, "date": TEST_DAY.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["total"] == len(body["overdue"]) + len(body["pre_visit"]) > 0
    assert len(body["overdue"]) <= WorklistConfig().capacity
    first = body["overdue"][0]
    assert first["rank"] == 1 and first["status"] == "open" and first["reasons"]
    assert not ({"full_name", "phone", "phone_number", "address"} & set(first))
    # second call reads the stored list, same ids
    r2 = client.get("/worklist", params={"facility_id": facility_id, "date": TEST_DAY.isoformat()})
    assert [i["id"] for i in r2.json()["overdue"]] == [i["id"] for i in body["overdue"]]


@needs_db
def test_call_result_validation_uses_simple_vocabulary(client, facility_id):
    body = client.get("/worklist", params={"facility_id": facility_id, "date": TEST_DAY.isoformat()}).json()
    appt = body["overdue"][0]["appointment_id"]
    assert client.post("/call-results", json={"appointment_id": appt, "result_type": "no_answer"}).status_code == 422
    assert client.post("/call-results", json={"appointment_id": appt, "result_type": "removed_from_overdue_list"}).status_code == 422
    assert client.post("/call-results", json={"appointment_id": appt, "result_type": "removed_from_overdue_list",
                                              "remove_reason": "busy"}).status_code == 422
    assert client.post("/call-results", json={"appointment_id": appt, "result_type": "agreed_to_visit",
                                              "remove_reason": "moved"}).status_code == 422
    assert client.post("/call-results", json={"appointment_id": "00000000-0000-0000-0000-000000000000",
                                              "result_type": "agreed_to_visit"}).status_code == 422


@needs_db
def test_call_result_updates_appointment_closes_item_and_survives_rebuild(client, facility_id):
    from app.db import engine
    body = client.get("/worklist", params={"facility_id": facility_id, "date": TEST_DAY.isoformat()}).json()
    item = body["overdue"][0]
    r = client.post("/call-results", json={"appointment_id": item["appointment_id"], "result_type": "agreed_to_visit",
                                           "worklist_item_id": item["id"]})
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["worklist_items_closed"] == 1
    with engine.connect() as c:
        a = c.execute(text("SELECT agreed_to_visit, status FROM appointments WHERE id = :id"), {"id": item["appointment_id"]}).one()
        cr = c.execute(text("SELECT result_type, patient_id::text FROM call_results WHERE id = :id"), {"id": res["call_result_id"]}).one()
    assert a.agreed_to_visit is True and a.status == "scheduled"
    assert cr.result_type == "agreed_to_visit" and cr.patient_id == item["patient_id"]

    # rebuild: the actioned item is kept, the patient is not re-listed, capacity is respected
    body2 = client.get("/worklist", params={"facility_id": facility_id, "date": TEST_DAY.isoformat(), "rebuild": True}).json()
    ids = [i["appointment_id"] for i in body2["overdue"]]
    assert ids.count(item["appointment_id"]) == 1
    done = [i for i in body2["overdue"] if i["appointment_id"] == item["appointment_id"]][0]
    assert done["status"] == "done" and done["call_result_id"] == res["call_result_id"]
    assert len(body2["overdue"]) <= WorklistConfig().capacity
    assert body2["counts"]["done"] == 1

    # remind_to_call_later sets remind_on; removal cancels the appointment with Simple's cancel_reason
    nxt = [i for i in body2["overdue"] if i["status"] == "open"][:2]
    r = client.post("/call-results", json={"appointment_id": nxt[0]["appointment_id"], "result_type": "remind_to_call_later",
                                           "remind_on": "2026-09-29"})
    assert r.status_code == 201
    r = client.post("/call-results", json={"appointment_id": nxt[1]["appointment_id"], "result_type": "removed_from_overdue_list",
                                           "remove_reason": "invalid_phone_number"})
    assert r.status_code == 201
    with engine.connect() as c:
        a1 = c.execute(text("SELECT remind_on FROM appointments WHERE id = :id"), {"id": nxt[0]["appointment_id"]}).scalar()
        a2 = c.execute(text("SELECT status, cancel_reason FROM appointments WHERE id = :id"), {"id": nxt[1]["appointment_id"]}).one()
    assert str(a1) == "2026-09-29"
    assert a2.status == "cancelled" and a2.cancel_reason == "invalid_phone_number"
    # skipping
    open_items = [i for i in client.get("/worklist", params={"facility_id": facility_id, "date": TEST_DAY.isoformat()}).json()["overdue"] if i["status"] == "open"]
    assert client.post(f"/worklist/items/{open_items[0]['id']}/skip").status_code == 204
    assert client.post(f"/worklist/items/{open_items[0]['id']}/skip").status_code == 404


@needs_db
def test_celery_task_builds_all_facilities_eagerly():
    from worker.celery_app import celery
    from worker.tasks import build_daily_worklists
    celery.conf.task_always_eager = True
    out = build_daily_worklists.apply(kwargs={"list_date": TEST_DAY.isoformat()}).get()
    assert out["list_date"] == TEST_DAY.isoformat()
    assert len(out["facilities"]) >= 1
    # second run is a no-op (already built)
    out2 = build_daily_worklists.apply(kwargs={"list_date": TEST_DAY.isoformat()}).get()
    assert all(v == -1 for v in out2["facilities"].values())
