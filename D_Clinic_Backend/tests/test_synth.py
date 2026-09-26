"""Invariants of the synthetic cohort generator. No database needed."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "synth"))
from generate import PROGRAM_END, Generator  # noqa: E402

END = pd.Timestamp(PROGRAM_END)


@pytest.fixture(scope="module")
def frames() -> dict[str, pd.DataFrame]:
    f = Generator(n_patients=800, seed=7).run()
    for t, col in [("blood_pressures", "recorded_at"), ("blood_sugars", "recorded_at"), ("patients", "recorded_at"),
                   ("communications", "device_created_at"), ("call_results", "device_created_at")]:
        f[t][col] = pd.to_datetime(f[t][col])
    f["appointments"]["scheduled_date"] = pd.to_datetime(f["appointments"]["scheduled_date"])
    f["appointments"]["device_created_at"] = pd.to_datetime(f["appointments"]["device_created_at"])
    return f


def test_deterministic_for_seed():
    a = Generator(n_patients=50, seed=3).run()
    b = Generator(n_patients=50, seed=3).run()
    assert a["appointments"]["id"].tolist() == b["appointments"]["id"].tolist()
    assert a["blood_pressures"]["systolic"].tolist() == b["blood_pressures"]["systolic"].tolist()


def test_every_patient_has_registration_bp_and_appointment(frames):
    p, bp, a = frames["patients"], frames["blood_pressures"], frames["appointments"]
    assert set(p.id) == set(bp.patient_id) == set(a.patient_id)


def test_no_visit_before_registration(frames):
    reg = frames["patients"].set_index("id")["recorded_at"]
    bp = frames["blood_pressures"]
    assert (bp.recorded_at.dt.normalize() >= bp.patient_id.map(reg).dt.normalize()).all()


def test_no_clinical_event_after_program_end(frames):
    assert (frames["blood_pressures"].recorded_at <= END + pd.Timedelta(days=1)).all()
    assert (frames["communications"].device_created_at <= END + pd.Timedelta(days=2)).all()


def test_no_bp_after_death(frames):
    dead = frames["patients"].query("status == 'dead'")
    cancelled = frames["appointments"].query("cancel_reason == 'dead'").set_index("patient_id")["device_updated_at"]
    bp = frames["blood_pressures"]
    for pid in dead.id:
        if pid in cancelled.index:
            assert (bp.loc[bp.patient_id == pid, "recorded_at"] <= pd.to_datetime(cancelled[pid])).all()


def test_appointment_booked_before_scheduled_and_monotone(frames):
    a = frames["appointments"].sort_values(["patient_id", "device_created_at"])
    assert (a.device_created_at.dt.normalize() <= a.scheduled_date).all()
    diffs = a.groupby("patient_id").scheduled_date.diff().dropna()
    assert (diffs > pd.Timedelta(0)).all()


def test_appointment_statuses_and_call_result_values(frames):
    assert set(frames["appointments"].status) <= {"scheduled", "visited", "cancelled"}
    cr = frames["call_results"]
    assert set(cr.result_type) <= {"agreed_to_visit", "remind_to_call_later", "removed_from_overdue_list"}
    assert cr.loc[cr.result_type != "removed_from_overdue_list", "remove_reason"].isna().all()
    assert cr.loc[cr.result_type == "removed_from_overdue_list", "remove_reason"].notna().all()


def test_exactly_one_active_protocol_ladder_per_active_patient(frames):
    rx = frames["prescription_drugs"].query("is_protocol_drug and not is_deleted")
    counts = rx.groupby("patient_id").size()
    assert counts.between(1, 3).all()  # ladder steps have 1..3 drugs


def test_missed_rate_in_expected_range(frames):
    a, bp = frames["appointments"], frames["blood_pressures"]
    due = a[a.scheduled_date <= END - pd.Timedelta(days=7)]
    d = bp.assign(d=bp.recorded_at.dt.normalize())[["patient_id", "d"]]
    m = due.merge(d, on="patient_id", how="left")
    hit = (m.d >= m.scheduled_date - pd.Timedelta(days=3)) & (m.d <= m.scheduled_date + pd.Timedelta(days=7))
    missed = 1 - hit.groupby(m.id).any().mean()
    assert 0.20 <= missed <= 0.35, missed


def test_sms_replies_have_truth_labels_and_stop_revokes_consent(frames):
    c = frames["communications"]
    inbound = c[c.direction == "inbound"]
    truth = frames["_truth_sms_intents"].set_index("communication_id")
    assert set(inbound.id) == set(truth.index)
    stopped = truth[truth.intent == "stop"].index
    pids = inbound[inbound.id.isin(stopped)].patient_id.unique()
    consent = frames["patients"].set_index("id").reminder_consent
    assert (consent.loc[pids] == "denied").all()


def test_identity_columns_are_not_in_truth_files(frames):
    for name in ("_truth_patients", "_truth_sms_intents"):
        cols = set(frames[name].columns)
        assert not cols & {"full_name", "number", "street_address", "date_of_birth"}
