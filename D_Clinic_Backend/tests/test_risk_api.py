"""Scoring, API and Celery task against the seeded database (skipped if unreachable)."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from ml.train import ARTIFACT_DIR, MODEL_VERSION


def _db_ok() -> bool:
    try:
        from app.db import engine
        with engine.connect() as c:
            return c.execute(text("SELECT count(*) FROM appointments")).scalar() > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ok() or not (ARTIFACT_DIR / f"{MODEL_VERSION}.joblib").exists(),
                                reason="needs seeded database and trained artifact")


@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_score_endpoint_returns_bands_basis_reasons_and_persists(client):
    from app.db import engine
    with engine.connect() as c:
        fid = str(c.execute(text("SELECT id FROM facilities LIMIT 1")).scalar())
        before = c.execute(text("SELECT count(*) FROM risk_scores")).scalar()
    r = client.post("/risk/score", json={"facility_id": fid, "horizon_days": 30, "as_of": "2026-09-26"})
    assert r.status_code == 200
    rows = r.json()
    assert rows, "expected upcoming appointments to score"
    assert {x["band"] for x in rows} <= {"low", "medium", "high"}
    assert {x["basis"] for x in rows} <= {"group", "mixed", "personal"}
    assert all(0 <= x["p_missed"] <= 1 for x in rows)
    assert all(x["model_version"] == MODEL_VERSION for x in rows)
    assert all(isinstance(x["reasons"], list) for x in rows)
    with engine.connect() as c:
        after = c.execute(text("SELECT count(*) FROM risk_scores")).scalar()
    assert after == before + len(rows)

    one = rows[0]
    g = client.get(f"/risk/appointments/{one['appointment_id']}")
    assert g.status_code == 200 and g.json()["appointment_id"] == one["appointment_id"]
    p = client.get(f"/risk/patients/{one['patient_id']}")
    assert p.status_code == 200 and len(p.json()) >= 1


def test_response_has_no_identity_fields(client):
    r = client.post("/risk/score", json={"horizon_days": 7, "as_of": "2026-09-26", "persist": False})
    keys = set().union(*(x.keys() for x in r.json())) if r.json() else set()
    assert not keys & {"full_name", "number", "phone", "address", "date_of_birth"}


def test_celery_task_runs_eagerly():
    from worker.celery_app import celery
    from worker.tasks import score_upcoming_appointments
    celery.conf.task_always_eager = True
    celery.conf.task_store_eager_result = False
    res = score_upcoming_appointments.apply(kwargs={"horizon_days": 14}).get()
    assert res["scored"] > 0 and set(res["bands"]) <= {"low", "medium", "high"}


def test_group_basis_rows_are_new_patients():
    from app.db import engine
    q = text("""SELECT r.basis, count(*) FROM latest_risk_scores r
                JOIN (SELECT patient_id, count(*) n FROM appointments GROUP BY patient_id) a USING (patient_id)
                WHERE a.n = 1 GROUP BY r.basis""")
    with engine.connect() as c:
        rows = dict(c.execute(q).all())
    assert set(rows) <= {"group"}, rows


def test_reasons_never_claim_bad_history_for_clean_patients():
    from app.db import engine
    q = text("""SELECT r.reasons FROM latest_risk_scores r
                JOIN (SELECT patient_id, count(*) n FROM appointments GROUP BY patient_id) a USING (patient_id)
                WHERE a.n = 1""")
    with engine.connect() as c:
        for (reasons,) in c.execute(q).all():
            assert "missed the last visit(s) in a row" not in reasons
            assert "number of past missed visits" not in reasons
