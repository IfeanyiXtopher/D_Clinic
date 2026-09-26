"""Appointment-level feature table for the missed-visit model.

Every feature is computed **as of the moment the appointment was booked**
(`appointments.device_created_at`), using only events recorded on or before
that time. This is what the program knows when it schedules the visit, and it
is the information available when the nightly job scores upcoming visits.

Label
-----
``missed = 1`` if no blood pressure was recorded in the window
``[scheduled_date - 3 days, scheduled_date + 7 days]``. Only appointments whose
window has closed by ``as_of`` are labelled; cancelled appointments (death,
migration) are excluded because they are not attendance behaviour.

Excluded on purpose
-------------------
Names, phone numbers, addresses, national IDs, and region/state/ethnicity.
Region is joined separately by the fairness audit only (see ``audit_columns``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

WINDOW_BEFORE = pd.Timedelta(days=3)
WINDOW_AFTER = pd.Timedelta(days=7)
FACILITY_RATE_PRIOR = 0.25  # used until a facility has its own resolved appointments

AGE_BINS = [0, 39, 49, 59, 69, 200]
AGE_LABELS = ["<40", "40-49", "50-59", "60-69", "70+"]

NUMERIC_FEATURES = [
    "lead_days",
    "prior_appointments",
    "prior_missed",
    "prior_miss_rate",
    "consecutive_misses",
    "months_in_program",
    "last_gap_days",
    "systolic",
    "diastolic",
    "systolic_change",
    "n_protocol_drugs",
    "prior_calls",
    "facility_prior_miss_rate",
]
BINARY_FEATURES = [
    "uncontrolled",
    "drug_changed_at_booking",
    "diabetic",
    "has_phone",
    "reminder_consent",
    "male",
    "rainy_season",
]
CATEGORICAL_FEATURES = [
    "age_band",
    "distance_band",
    "facility_id",
    "last_call_result",
    "scheduled_weekday",
]
FEATURES = NUMERIC_FEATURES + BINARY_FEATURES + CATEGORICAL_FEATURES

# Columns carried along for evaluation and audits but never given to the model.
AUDIT_COLUMNS = ["appointment_id", "patient_id", "scheduled_date", "booked_at", "gender", "region", "age"]

FORBIDDEN_COLUMNS = {"full_name", "number", "street_address", "village_or_colony", "date_of_birth", "region", "state"}


@dataclass
class FeatureTable:
    frame: pd.DataFrame  # AUDIT_COLUMNS + FEATURES + label columns

    @property
    def X(self) -> pd.DataFrame:
        return self.frame[FEATURES]

    @property
    def y(self) -> pd.Series:
        return self.frame["missed"].astype(int)


# --------------------------------------------------------------------------- loading


def load_tables_from_db(engine) -> dict[str, pd.DataFrame]:
    """Read the columns the pipeline needs. Identity columns are never selected."""
    sql = {
        "patients": """SELECT p.id AS patient_id, p.age, p.gender, p.status, p.reminder_consent,
                              p.recorded_at AS registered_at, p.assigned_facility_id,
                              a.zone AS distance_band, a.state AS region,
                              (mh.diabetes = 'yes') AS diabetic,
                              EXISTS (SELECT 1 FROM patient_phone_numbers ph
                                      WHERE ph.patient_id = p.id AND ph.active) AS has_phone
                       FROM patients p
                       JOIN addresses a ON a.patient_id = p.id
                       JOIN medical_histories mh ON mh.patient_id = p.id""",
        "appointments": """SELECT id AS appointment_id, patient_id, facility_id, scheduled_date, status,
                                  remind_on, device_created_at AS booked_at, device_updated_at FROM appointments""",
        "blood_pressures": "SELECT patient_id, systolic, diastolic, recorded_at FROM blood_pressures WHERE deleted_at IS NULL",
        "prescription_drugs": """SELECT patient_id, device_created_at, is_deleted, device_updated_at
                                 FROM prescription_drugs WHERE is_protocol_drug""",
        "call_results": "SELECT patient_id, appointment_id, result_type, remove_reason, device_created_at FROM call_results",
    }
    return {k: pd.read_sql(v, engine) for k, v in sql.items()}


def load_tables_from_csv(directory) -> dict[str, pd.DataFrame]:
    """Same shape as :func:`load_tables_from_db`, from generator CSVs (used in tests)."""
    from pathlib import Path

    d = Path(directory)
    p = pd.read_csv(d / "patients.csv")
    addr = pd.read_csv(d / "addresses.csv")[["patient_id", "zone", "state"]]
    mh = pd.read_csv(d / "medical_histories.csv")[["patient_id", "diabetes"]]
    ph = pd.read_csv(d / "patient_phone_numbers.csv")[["patient_id"]].drop_duplicates()
    patients = (
        p.rename(columns={"id": "patient_id", "recorded_at": "registered_at"})
        [["patient_id", "age", "gender", "status", "reminder_consent", "registered_at", "assigned_facility_id"]]
        .merge(addr.rename(columns={"zone": "distance_band", "state": "region"}), on="patient_id")
        .merge(mh.assign(diabetic=mh.diabetes == "yes")[["patient_id", "diabetic"]], on="patient_id")
        .assign(has_phone=lambda x: x.patient_id.isin(ph.patient_id))
    )
    a = pd.read_csv(d / "appointments.csv").rename(columns={"id": "appointment_id", "device_created_at": "booked_at"})
    if "remind_on" not in a.columns:
        a["remind_on"] = pd.NaT
    rx = pd.read_csv(d / "prescription_drugs.csv")
    return {
        "patients": patients,
        "appointments": a[["appointment_id", "patient_id", "facility_id", "scheduled_date", "status",
                           "remind_on", "booked_at", "device_updated_at"]],
        "blood_pressures": pd.read_csv(d / "blood_pressures.csv")[["patient_id", "systolic", "diastolic", "recorded_at"]],
        "prescription_drugs": rx[rx.is_protocol_drug][["patient_id", "device_created_at", "is_deleted", "device_updated_at"]],
        "call_results": pd.read_csv(d / "call_results.csv")[["patient_id", "appointment_id", "result_type", "remove_reason", "device_created_at"]],
    }


# --------------------------------------------------------------------------- building


def _to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s)


def label_appointments(appts: pd.DataFrame, bps: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Attach ``missed`` (nullable boolean) and ``label_known`` to appointments."""
    a = appts.copy()
    a["scheduled_date"] = _to_dt(a.scheduled_date).dt.normalize()
    bp_days = bps.assign(d=_to_dt(bps.recorded_at).dt.normalize())[["patient_id", "d"]].drop_duplicates()
    m = a[["appointment_id", "patient_id", "scheduled_date"]].merge(bp_days, on="patient_id", how="left")
    hit = (m.d >= m.scheduled_date - WINDOW_BEFORE) & (m.d <= m.scheduled_date + WINDOW_AFTER)
    attended = hit.groupby(m.appointment_id).any()
    a["attended"] = a.appointment_id.map(attended).fillna(False).astype(bool)
    a["label_known"] = (a.scheduled_date + WINDOW_AFTER <= as_of) | a.attended
    a["missed"] = np.where(a.label_known, ~a.attended, np.nan)
    return a


def build_feature_table(tables: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> FeatureTable:
    as_of = pd.Timestamp(as_of).normalize()
    patients = tables["patients"].copy()
    bps = tables["blood_pressures"].copy()
    rx = tables["prescription_drugs"].copy()
    calls = tables["call_results"].copy()

    a = label_appointments(tables["appointments"], bps, as_of)
    a["booked_at"] = _to_dt(a.booked_at)
    a["booked_date"] = a.booked_at.dt.normalize()
    a = a[a.status != "cancelled"].copy()
    a = a.sort_values(["patient_id", "scheduled_date", "booked_at"]).reset_index(drop=True)

    # ---- history of previous appointments (only those resolved by booking time)
    a["lead_days"] = (a.scheduled_date - a.booked_date).dt.days
    grp = a.groupby("patient_id", sort=False)
    # A previous appointment is always resolved by the time the next one is booked: bookings happen
    # at visits, and a visit inside the previous window means it was attended.
    a["prior_appointments"] = grp.cumcount()
    a["prior_missed"] = grp["missed"].transform(lambda s: s.fillna(0).cumsum().shift(1).fillna(0))
    a["prior_miss_rate"] = np.where(a.prior_appointments > 0, a.prior_missed / a.prior_appointments.clip(lower=1), np.nan)

    def _streak(s: pd.Series) -> pd.Series:
        """Number of consecutive misses immediately before each appointment."""
        res, run = [], 0
        for v in s.tolist():
            res.append(run)
            run = run + 1 if v == 1 else 0
        return pd.Series(res, index=s.index)

    a["consecutive_misses"] = grp["missed"].transform(lambda s: _streak(s.fillna(0)))
    a["last_gap_days"] = grp["booked_date"].diff().dt.days.fillna(0)

    # ---- patient statics
    p = patients.copy()
    p["registered_at"] = _to_dt(p.registered_at)
    a = a.merge(
        p[["patient_id", "age", "gender", "reminder_consent", "registered_at", "distance_band", "region", "diabetic", "has_phone"]],
        on="patient_id", how="left",
    )
    a["months_in_program"] = ((a.booked_date - a.registered_at).dt.days / 30.44).clip(lower=0)
    a["age_band"] = pd.cut(a.age, AGE_BINS, labels=AGE_LABELS).astype(str)
    a["male"] = (a.gender == "male").astype(int)
    a["diabetic"] = a.diabetic.astype(int)
    a["has_phone"] = a.has_phone.astype(int)
    a["reminder_consent"] = (a.reminder_consent == "granted").astype(int)
    a["rainy_season"] = a.scheduled_date.dt.month.isin([6, 7, 8, 9]).astype(int)
    a["scheduled_weekday"] = a.scheduled_date.dt.day_name().str[:3]

    # ---- latest BP as of the booking *day* (the visit BP is recorded the same day the next
    # appointment is created) and change vs previous. Later calendar days must not leak.
    bps["recorded_at"] = _to_dt(bps.recorded_at)
    bps = bps.sort_values(["patient_id", "recorded_at"])
    bps["prev_systolic"] = bps.groupby("patient_id").systolic.shift(1)
    bps["ts"] = bps.recorded_at.dt.normalize() + pd.Timedelta(hours=23, minutes=59)
    a = a.sort_values("booked_at")
    a["_key"] = a.booked_date + pd.Timedelta(hours=23, minutes=59)
    a = pd.merge_asof(a, bps[["patient_id", "ts", "systolic", "diastolic", "prev_systolic"]].sort_values("ts"),
                      left_on="_key", right_on="ts", by="patient_id", direction="backward")
    a["systolic_change"] = (a.systolic - a.prev_systolic).fillna(0)
    a["uncontrolled"] = ((a.systolic >= 140) | (a.diastolic >= 90)).astype(int)
    a = a.drop(columns=["ts", "prev_systolic"])

    # ---- protocol drugs active at booking: ladder step events
    rx["device_created_at"] = _to_dt(rx.device_created_at)
    steps = rx.groupby(["patient_id", rx.device_created_at.dt.normalize().rename("step_date")]).size().rename("n_protocol_drugs").reset_index()
    steps["ts"] = steps.step_date + pd.Timedelta(hours=23, minutes=59)
    steps = steps.sort_values("ts")
    steps["step_index"] = steps.groupby("patient_id").cumcount()
    a = pd.merge_asof(a.sort_values("_key"), steps[["patient_id", "ts", "n_protocol_drugs", "step_date", "step_index"]],
                      left_on="_key", right_on="ts", by="patient_id", direction="backward")
    a["n_protocol_drugs"] = a.n_protocol_drugs.fillna(1)
    a["drug_changed_at_booking"] = ((a.step_date == a.booked_date) & (a.step_index > 0)).astype(int)
    a = a.drop(columns=["ts", "step_date", "step_index"])

    # ---- calls before booking
    calls["device_created_at"] = _to_dt(calls.device_created_at)
    calls = calls.sort_values("device_created_at")
    calls["prior_calls"] = calls.groupby("patient_id").cumcount() + 1
    calls = calls[["patient_id", "result_type", "device_created_at", "prior_calls"]]
    a = pd.merge_asof(a.sort_values("booked_at"), calls.rename(columns={"device_created_at": "ts", "result_type": "last_call_result"}),
                      left_on="booked_at", right_on="ts", by="patient_id", direction="backward")
    a["prior_calls"] = a.prior_calls.fillna(0)
    a["last_call_result"] = a.last_call_result.fillna("none")
    a = a.drop(columns=["ts"])

    # ---- facility prior miss rate, time-aware (only appointments resolved before booking)
    resolved = a[a.label_known].copy()
    resolved["resolved_at"] = resolved.scheduled_date + WINDOW_AFTER
    resolved = resolved.sort_values("resolved_at")
    resolved["fac_cum_n"] = resolved.groupby("facility_id").cumcount() + 1
    resolved["fac_cum_missed"] = resolved.groupby("facility_id").missed.cumsum()
    resolved["fac_rate"] = resolved.fac_cum_missed / resolved.fac_cum_n
    a = pd.merge_asof(a.sort_values("booked_at"), resolved[["facility_id", "resolved_at", "fac_rate"]].rename(columns={"resolved_at": "ts"}),
                      left_on="booked_at", right_on="ts", by="facility_id", direction="backward", allow_exact_matches=False)
    # Before a facility has any resolved appointment, use a fixed prior. Never a dataset-wide mean:
    # that would let future outcomes leak into early rows (caught by tests/test_features.py).
    a["facility_prior_miss_rate"] = a.fac_rate.fillna(FACILITY_RATE_PRIOR)
    a = a.drop(columns=["ts", "fac_rate", "_key"])

    a["facility_id"] = a.facility_id.astype(str)
    a["distance_band"] = a.distance_band.astype(str)
    cols = AUDIT_COLUMNS + FEATURES + ["missed", "label_known", "attended", "status"]
    out = a[cols].sort_values(["scheduled_date", "appointment_id"]).reset_index(drop=True)
    assert not (set(out.columns) & (FORBIDDEN_COLUMNS - {"region"})), "identity column leaked into feature table"
    return FeatureTable(out)


def labelled(ft: FeatureTable) -> FeatureTable:
    f = ft.frame
    return FeatureTable(f[f.label_known].copy().reset_index(drop=True))
