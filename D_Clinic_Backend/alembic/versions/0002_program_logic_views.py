"""program-logic views: latest BP, control status, overdue, lost to follow-up

Definitions follow Simple / WHO HEARTS indicators. See docs/definitions.md.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


VIEWS = {
    # Latest non-deleted BP per patient.
    "latest_blood_pressures": """
        SELECT DISTINCT ON (bp.patient_id)
               bp.patient_id, bp.id AS blood_pressure_id, bp.systolic, bp.diastolic,
               bp.recorded_at, bp.facility_id
        FROM blood_pressures bp
        WHERE bp.deleted_at IS NULL
        ORDER BY bp.patient_id, bp.recorded_at DESC
    """,
    # Control status at the latest BP (HEARTS: < 140/90).
    "bp_controlled_latest": """
        SELECT l.patient_id, l.systolic, l.diastolic, l.recorded_at,
               (l.systolic < 140 AND l.diastolic < 90) AS controlled
        FROM latest_blood_pressures l
    """,
    # Latest appointment per patient (by scheduled_date, then booking time).
    "latest_appointments": """
        SELECT DISTINCT ON (a.patient_id)
               a.patient_id, a.id AS appointment_id, a.facility_id, a.scheduled_date, a.status,
               a.remind_on, a.agreed_to_visit, a.device_created_at AS booked_at
        FROM appointments a
        ORDER BY a.patient_id, a.scheduled_date DESC, a.device_created_at DESC
    """,
    # Patients "under care": alive, active, and seen (BP recorded) in the last 12 months.
    "patients_under_care": """
        SELECT p.id AS patient_id, p.assigned_facility_id, l.recorded_at AS last_visit_at
        FROM patients p
        JOIN latest_blood_pressures l ON l.patient_id = p.id
        WHERE p.status = 'active' AND p.deleted_at IS NULL
          AND l.recorded_at >= (CURRENT_DATE - INTERVAL '365 days')
    """,
    # Lost to follow-up: active but no visit in the last 12 months, registered > 12 months ago.
    "lost_to_follow_up": """
        SELECT p.id AS patient_id, p.assigned_facility_id, l.recorded_at AS last_visit_at,
               (CURRENT_DATE - l.recorded_at::date) AS days_since_last_visit
        FROM patients p
        JOIN latest_blood_pressures l ON l.patient_id = p.id
        WHERE p.status = 'active' AND p.deleted_at IS NULL
          AND l.recorded_at <  (CURRENT_DATE - INTERVAL '365 days')
          AND p.recorded_at <  (CURRENT_DATE - INTERVAL '365 days')
    """,
    # Overdue: latest appointment is still 'scheduled', its date has passed, and the patient
    # has not visited on/after that date. Simple's *overdue list* additionally requires a
    # phone; the *follow-up list* does not. Both flags are exposed.
    "overdue_patients": """
        SELECT uc.patient_id, uc.assigned_facility_id, la.appointment_id, la.scheduled_date,
               (CURRENT_DATE - la.scheduled_date) AS days_overdue,
               la.remind_on, la.agreed_to_visit,
               EXISTS (SELECT 1 FROM patient_phone_numbers ph
                       WHERE ph.patient_id = uc.patient_id AND ph.active) AS has_phone,
               cr.result_type AS last_call_result, cr.remove_reason AS last_call_remove_reason,
               cr.device_created_at AS last_called_at,
               bc.systolic, bc.diastolic, bc.controlled
        FROM patients_under_care uc
        JOIN latest_appointments la ON la.patient_id = uc.patient_id
        JOIN bp_controlled_latest bc ON bc.patient_id = uc.patient_id
        LEFT JOIN LATERAL (
            SELECT c.result_type, c.remove_reason, c.device_created_at
            FROM call_results c WHERE c.appointment_id = la.appointment_id
            ORDER BY c.device_created_at DESC LIMIT 1
        ) cr ON TRUE
        WHERE la.status = 'scheduled'
          AND la.scheduled_date < CURRENT_DATE
          AND uc.last_visit_at::date < la.scheduled_date
    """,
}

# creation order matters because views depend on each other
ORDER = [
    "latest_blood_pressures",
    "bp_controlled_latest",
    "latest_appointments",
    "patients_under_care",
    "lost_to_follow_up",
    "overdue_patients",
]


def upgrade() -> None:
    for name in ORDER:
        op.execute(f"CREATE OR REPLACE VIEW {name} AS {VIEWS[name]}")


def downgrade() -> None:
    for name in reversed(ORDER):
        op.execute(f"DROP VIEW IF EXISTS {name}")
