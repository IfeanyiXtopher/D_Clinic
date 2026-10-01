"""Load structured clinical fields for a packet. Identity columns are never selected."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Columns this module must never mention in SQL (enforced by tests).
# full_name, date_of_birth, street_address, village_or_colony, patient_phone_numbers.number


def fetch_clinical_record(engine: Engine, patient_id: str, as_of: date | None = None) -> dict | None:
    """Return a de-id-safe record, or None if the patient does not exist."""
    as_of = as_of or date.today()
    window_start = as_of - timedelta(days=365)

    with engine.connect() as c:
        patient = c.execute(
            text(
                """SELECT id, age, gender, status, reminder_consent, recorded_at
                   FROM patients WHERE id = :id AND deleted_at IS NULL"""
            ),
            {"id": patient_id},
        ).mappings().first()
        if not patient:
            return None

        hx = c.execute(
            text(
                """SELECT hypertension, diabetes FROM medical_histories
                   WHERE patient_id = :id ORDER BY created_at DESC LIMIT 1"""
            ),
            {"id": patient_id},
        ).mappings().first()

        bps = c.execute(
            text(
                """SELECT systolic, diastolic, recorded_at FROM blood_pressures
                   WHERE patient_id = :id AND deleted_at IS NULL AND recorded_at::date <= :as_of
                   ORDER BY recorded_at DESC LIMIT 6"""
            ),
            {"id": patient_id, "as_of": as_of},
        ).mappings().all()

        sugars = c.execute(
            text(
                """SELECT blood_sugar_type, blood_sugar_value, recorded_at FROM blood_sugars
                   WHERE patient_id = :id AND deleted_at IS NULL AND recorded_at::date <= :as_of
                   ORDER BY recorded_at DESC LIMIT 4"""
            ),
            {"id": patient_id, "as_of": as_of},
        ).mappings().all()

        drugs = c.execute(
            text(
                """SELECT name, dosage, frequency FROM prescription_drugs
                   WHERE patient_id = :id AND is_deleted = false
                   ORDER BY device_updated_at DESC"""
            ),
            {"id": patient_id},
        ).mappings().all()

        visits_12m = c.execute(
            text(
                """SELECT count(*) FROM blood_pressures
                   WHERE patient_id = :id AND deleted_at IS NULL
                     AND recorded_at::date BETWEEN :lo AND :as_of"""
            ),
            {"id": patient_id, "lo": window_start, "as_of": as_of},
        ).scalar()

        last_visit = c.execute(
            text(
                """SELECT max(recorded_at) FROM blood_pressures
                   WHERE patient_id = :id AND deleted_at IS NULL AND recorded_at::date <= :as_of"""
            ),
            {"id": patient_id, "as_of": as_of},
        ).scalar()

        # Missed in the last year: scheduled appointments whose window has closed with no BP in window.
        missed_12m = c.execute(
            text(
                """SELECT count(*) FROM appointments a
                   WHERE a.patient_id = :id
                     AND a.scheduled_date BETWEEN :lo AND :as_of
                     AND a.scheduled_date <= :as_of - 7
                     AND a.status <> 'cancelled'
                     AND a.device_created_at::date <= :as_of
                     AND NOT EXISTS (
                       SELECT 1 FROM blood_pressures b
                       WHERE b.patient_id = a.patient_id AND b.deleted_at IS NULL
                         AND b.recorded_at::date BETWEEN a.scheduled_date - 3 AND a.scheduled_date + 7
                     )"""
            ),
            {"id": patient_id, "lo": window_start, "as_of": as_of},
        ).scalar()

        next_appt = c.execute(
            text(
                """SELECT scheduled_date, status FROM appointments
                   WHERE patient_id = :id AND scheduled_date >= :as_of
                     AND status = 'scheduled' AND device_created_at::date <= :as_of
                   ORDER BY scheduled_date LIMIT 1"""
            ),
            {"id": patient_id, "as_of": as_of},
        ).mappings().first()

        open_overdue = c.execute(
            text(
                """SELECT scheduled_date FROM appointments
                   WHERE patient_id = :id AND status = 'scheduled' AND scheduled_date < :as_of
                     AND device_created_at::date <= :as_of
                   ORDER BY scheduled_date DESC LIMIT 1"""
            ),
            {"id": patient_id, "as_of": as_of},
        ).mappings().first()

        last_call = c.execute(
            text(
                """SELECT result_type, remove_reason, device_created_at AS recorded_at
                   FROM call_results
                   WHERE patient_id = :id AND device_created_at::date <= :as_of
                   ORDER BY device_created_at DESC LIMIT 1"""
            ),
            {"id": patient_id, "as_of": as_of},
        ).mappings().first()

        risk = c.execute(
            text(
                """SELECT band, basis, reasons FROM latest_risk_scores
                   WHERE patient_id = :id AND scheduled_date <= :as_of + 60
                   ORDER BY scheduled_date DESC LIMIT 1"""
            ),
            {"id": patient_id, "as_of": as_of},
        ).mappings().first()

    days_overdue = None
    program_status = "under_care"
    if patient["status"] != "active":
        program_status = patient["status"]
    elif last_visit is None or _as_date(last_visit) < as_of - timedelta(days=365):
        program_status = "lost_to_follow_up"
    elif open_overdue:
        days_overdue = (as_of - _as_date(open_overdue["scheduled_date"])).days
        program_status = "overdue"
    elif next_appt:
        program_status = "pre_visit"

    return {
        "age": patient["age"],
        "gender": patient["gender"],
        "hypertension": hx["hypertension"] if hx else "yes",
        "diabetes": hx["diabetes"] if hx else "no",
        "bp_history": [dict(r) for r in bps],
        "bs_history": [dict(r) for r in sugars],
        "drugs": [dict(r) for r in drugs],
        "attendance": {
            "visits_12m": int(visits_12m or 0),
            "missed_12m": int(missed_12m or 0),
            "last_visit_at": last_visit,
            "next_scheduled_at": next_appt["scheduled_date"] if next_appt else None,
            "days_overdue": days_overdue,
        },
        "last_call": dict(last_call) if last_call else None,
        "risk": dict(risk) if risk else None,
        "program_status": program_status,
    }


def _as_date(x) -> date:
    from datetime import datetime

    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])
