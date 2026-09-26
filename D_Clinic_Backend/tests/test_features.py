"""Feature pipeline: no leakage from the future, no identity columns, sane values."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ml.features import AUDIT_COLUMNS, FEATURES, FORBIDDEN_COLUMNS, build_feature_table, labelled, load_tables_from_csv

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "synth" / "sample"
AS_OF = pd.Timestamp("2026-09-26")


@pytest.fixture(scope="module")
def tables():
    return load_tables_from_csv(SAMPLE)


@pytest.fixture(scope="module")
def ft(tables):
    return build_feature_table(tables, AS_OF)


def test_no_identity_columns(ft):
    cols = set(ft.frame.columns)
    assert not (cols & (FORBIDDEN_COLUMNS - {"region"}))
    assert "region" not in FEATURES  # audit-only column
    assert all(c in ft.frame.columns for c in FEATURES + AUDIT_COLUMNS)


def test_label_definition(ft, tables):
    f = labelled(ft).frame
    bps = tables["blood_pressures"].assign(d=pd.to_datetime(tables["blood_pressures"].recorded_at).dt.normalize())
    row = f.iloc[0]
    days = bps[bps.patient_id == row.patient_id].d
    sd = pd.Timestamp(row.scheduled_date)
    attended = ((days >= sd - pd.Timedelta(days=3)) & (days <= sd + pd.Timedelta(days=7))).any()
    assert bool(row.missed) == (not attended)


def test_unresolved_windows_are_not_labelled(ft):
    f = ft.frame
    future = f[pd.to_datetime(f.scheduled_date) + pd.Timedelta(days=7) > AS_OF]
    assert (~future.label_known | future.attended).all()


def test_cancelled_appointments_excluded(ft):
    assert (ft.frame.status != "cancelled").all()


def test_features_do_not_change_when_future_events_are_added(tables):
    """Leakage test: adding events after booking must not alter the features of earlier appointments."""
    base = build_feature_table(tables, AS_OF).frame.set_index("appointment_id")
    t2 = {k: v.copy() for k, v in tables.items()}
    # inject a late BP, a late call and a late prescription for every patient
    late = pd.Timestamp("2026-09-20 10:00")
    pids = t2["patients"].patient_id
    t2["blood_pressures"] = pd.concat([t2["blood_pressures"], pd.DataFrame(
        {"patient_id": pids, "systolic": 199, "diastolic": 120, "recorded_at": late})])
    t2["call_results"] = pd.concat([t2["call_results"], pd.DataFrame(
        {"patient_id": pids, "result_type": "removed_from_overdue_list", "device_created_at": late})])
    t2["prescription_drugs"] = pd.concat([t2["prescription_drugs"], pd.DataFrame(
        {"patient_id": pids, "device_created_at": late, "is_deleted": False, "device_updated_at": late})])
    new = build_feature_table(t2, AS_OF).frame.set_index("appointment_id")
    early = base[pd.to_datetime(base.booked_at) < late].index
    pd.testing.assert_frame_equal(base.loc[early, FEATURES], new.loc[early, FEATURES], check_like=True)


def test_history_features_are_strictly_prior(ft):
    f = ft.frame.sort_values(["patient_id", "scheduled_date"])
    first = f.groupby("patient_id").head(1)
    assert (first.prior_appointments == 0).all()
    assert (first.prior_missed == 0).all()
    assert first.prior_miss_rate.isna().all()
    assert (first.consecutive_misses == 0).all()


def test_value_ranges(ft):
    f = ft.frame
    assert f.lead_days.between(1, 400).all()
    assert f.n_protocol_drugs.between(1, 3).all()
    assert set(f.age_band) <= {"<40", "40-49", "50-59", "60-69", "70+"}
    assert set(f.distance_band) <= {"near", "mid", "far"}
    assert set(f.last_call_result) <= {"none", "agreed_to_visit", "remind_to_call_later", "removed_from_overdue_list"}
    assert f.systolic.notna().all()
