"""Appointment tools. Called only by the state machine, never by the model."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from chatbot.dates import next_weekdays


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_phone(number: str) -> str:
    return hashlib.sha256(number.encode("utf-8")).hexdigest()


@dataclass
class AppointmentView:
    id: str
    patient_id: str
    facility_id: str
    scheduled_date: date
    status: str
    agreed_to_visit: bool | None = None


@dataclass
class StaffTask:
    id: str
    patient_id: str | None
    kind: str
    created_at: datetime = field(default_factory=_now)
    status: str = "open"


class MemoryTools:
    """In-memory tools for tests and scripted eval. Same methods as DbTools."""

    def __init__(self, *, as_of: date | None = None):
        self.as_of = as_of or date(2026, 9, 26)
        self.appointments: dict[str, AppointmentView] = {}
        self.consent: dict[str, str] = {}
        self.tasks: list[StaffTask] = []
        self.messages: list[dict] = []
        self.outbox: list[dict] = []

    def add_patient(self, patient_id: str, *, facility_id: str = "fac-1",
                    scheduled: date | None = None, consent: str = "granted") -> AppointmentView:
        appt = AppointmentView(
            id=f"a-{patient_id}",
            patient_id=patient_id,
            facility_id=facility_id,
            scheduled_date=scheduled or (self.as_of + timedelta(days=10)),
            status="scheduled",
        )
        self.appointments[appt.id] = appt
        self.consent[patient_id] = consent
        return appt

    def current_appointment(self, patient_id: str) -> AppointmentView | None:
        open_ = [a for a in self.appointments.values()
                 if a.patient_id == patient_id and a.status == "scheduled"]
        if not open_:
            return None
        upcoming = [a for a in open_ if a.scheduled_date >= self.as_of]
        pool = upcoming or open_
        return sorted(pool, key=lambda a: a.scheduled_date)[0]

    def get_available_slots(self, facility_id: str, as_of: date, n: int = 3,
                            skip: date | None = None) -> list[date]:
        return next_weekdays(as_of, n, skip=skip)

    def book(self, appointment_id: str) -> AppointmentView:
        a = self.appointments[appointment_id]
        a.agreed_to_visit = True
        return a

    def reschedule(self, appointment_id: str, new_date: date) -> AppointmentView:
        old = self.appointments[appointment_id]
        old.status = "cancelled"
        new = AppointmentView(
            id=str(uuid.uuid4()),
            patient_id=old.patient_id,
            facility_id=old.facility_id,
            scheduled_date=new_date,
            status="scheduled",
            agreed_to_visit=True,
        )
        self.appointments[new.id] = new
        return new

    def cancel(self, appointment_id: str, reason: str = "other") -> AppointmentView:
        a = self.appointments[appointment_id]
        a.status = "cancelled"
        return a

    def set_consent(self, patient_id: str, value: str) -> None:
        self.consent[patient_id] = value

    def create_staff_task(self, patient_id: str | None, kind: str) -> StaffTask:
        t = StaffTask(id=str(uuid.uuid4()), patient_id=patient_id, kind=kind)
        self.tasks.append(t)
        return t

    def record_reply(self, patient_id: str | None, body: str, *, direction: str,
                     appointment_id: str | None, language: str, communication_type: str = "sms") -> None:
        row = {
            "patient_id": patient_id, "body": body, "direction": direction,
            "appointment_id": appointment_id, "language": language,
            "communication_type": communication_type, "at": _now(),
        }
        self.messages.append(row)
        if direction == "outbound":
            self.outbox.append(row)


class DbTools:
    """Postgres-backed tools used by the API."""

    def __init__(self, engine, as_of: date | None = None):
        self.engine = engine
        self.as_of = as_of or date.today()

    def resolve_phone(self, number: str) -> str | None:
        from sqlalchemy import text

        digits = "".join(ch for ch in number if ch.isdigit())
        if digits.startswith("234") and len(digits) == 13:
            digits = "0" + digits[3:]
        with self.engine.connect() as c:
            pid = c.execute(
                text(
                    """SELECT patient_id FROM patient_phone_numbers
                       WHERE translate(number, ' -+', '') IN (:a, :b) AND active = true
                       LIMIT 1"""
                ),
                {"a": digits, "b": number.strip()},
            ).scalar()
        return str(pid) if pid else None

    def current_appointment(self, patient_id: str) -> AppointmentView | None:
        from sqlalchemy import text

        with self.engine.connect() as c:
            row = c.execute(
                text(
                    """SELECT id, patient_id, facility_id, scheduled_date, status, agreed_to_visit
                       FROM appointments
                       WHERE patient_id = :p AND status = 'scheduled'
                       ORDER BY CASE WHEN scheduled_date >= :d THEN 0 ELSE 1 END, scheduled_date
                       LIMIT 1"""
                ),
                {"p": patient_id, "d": self.as_of},
            ).mappings().first()
        if not row:
            return None
        return AppointmentView(
            id=str(row["id"]), patient_id=str(row["patient_id"]), facility_id=str(row["facility_id"]),
            scheduled_date=row["scheduled_date"], status=row["status"],
            agreed_to_visit=row["agreed_to_visit"],
        )

    def get_available_slots(self, facility_id: str, as_of: date, n: int = 3,
                            skip: date | None = None) -> list[date]:
        return next_weekdays(as_of, n, skip=skip)

    def book(self, appointment_id: str) -> AppointmentView:
        from sqlalchemy import text

        now = _now()
        with self.engine.begin() as c:
            c.execute(
                text("UPDATE appointments SET agreed_to_visit = true, remind_on = NULL, device_updated_at = :t WHERE id = :id"),
                {"id": appointment_id, "t": now},
            )
        appt = self._get(appointment_id)
        assert appt
        return appt

    def reschedule(self, appointment_id: str, new_date: date) -> AppointmentView:
        from sqlalchemy import text

        now = _now()
        old = self._get(appointment_id)
        if not old:
            raise KeyError(appointment_id)
        new_id = str(uuid.uuid4())
        with self.engine.begin() as c:
            c.execute(
                text(
                    """UPDATE appointments SET status = 'cancelled', cancel_reason = 'other',
                       device_updated_at = :t WHERE id = :id"""
                ),
                {"id": appointment_id, "t": now},
            )
            c.execute(
                text(
                    """INSERT INTO appointments (
                           id, patient_id, facility_id, creation_facility_id, scheduled_date, status,
                           agreed_to_visit, appointment_type, device_created_at, device_updated_at
                       ) VALUES (
                           :id, :p, :f, :f, :d, 'scheduled', true, 'manual', :t, :t
                       )"""
                ),
                {"id": new_id, "p": old.patient_id, "f": old.facility_id, "d": new_date, "t": now},
            )
        appt = self._get(new_id)
        assert appt
        return appt

    def cancel(self, appointment_id: str, reason: str = "other") -> AppointmentView:
        from sqlalchemy import text

        with self.engine.begin() as c:
            c.execute(
                text(
                    """UPDATE appointments SET status = 'cancelled', cancel_reason = :r, device_updated_at = :t
                       WHERE id = :id"""
                ),
                {"id": appointment_id, "r": reason, "t": _now()},
            )
        appt = self._get(appointment_id)
        assert appt
        return appt

    def set_consent(self, patient_id: str, value: str) -> None:
        from sqlalchemy import text

        with self.engine.begin() as c:
            c.execute(text("UPDATE patients SET reminder_consent = :v WHERE id = :id"),
                      {"v": value, "id": patient_id})

    def create_staff_task(self, patient_id: str | None, kind: str) -> StaffTask:
        from sqlalchemy import text

        tid = str(uuid.uuid4())
        now = _now()
        with self.engine.begin() as c:
            c.execute(
                text(
                    """INSERT INTO staff_tasks (id, patient_id, kind, status, created_at)
                       VALUES (:id, :p, :k, 'open', :t)"""
                ),
                {"id": tid, "p": patient_id, "k": kind, "t": now},
            )
        return StaffTask(id=tid, patient_id=patient_id, kind=kind, created_at=now)

    def record_reply(self, patient_id: str | None, body: str, *, direction: str,
                     appointment_id: str | None, language: str, communication_type: str = "sms") -> None:
        from sqlalchemy import text

        if not patient_id:
            return
        with self.engine.begin() as c:
            c.execute(
                text(
                    """INSERT INTO communications (
                           id, patient_id, appointment_id, communication_type, direction, body,
                           language, delivery_status, device_created_at
                       ) VALUES (
                           :id, :p, :a, :ct, :dir, :body, :lang, :st, :t
                       )"""
                ),
                {
                    "id": str(uuid.uuid4()), "p": patient_id, "a": appointment_id,
                    "ct": communication_type, "dir": direction, "body": body, "lang": language,
                    "st": "sent" if direction == "outbound" else "received", "t": _now(),
                },
            )

    def _get(self, appointment_id: str) -> AppointmentView | None:
        from sqlalchemy import text

        with self.engine.connect() as c:
            row = c.execute(
                text(
                    """SELECT id, patient_id, facility_id, scheduled_date, status, agreed_to_visit
                       FROM appointments WHERE id = :id"""
                ),
                {"id": appointment_id},
            ).mappings().first()
        if not row:
            return None
        return AppointmentView(
            id=str(row["id"]), patient_id=str(row["patient_id"]), facility_id=str(row["facility_id"]),
            scheduled_date=row["scheduled_date"], status=row["status"],
            agreed_to_visit=row["agreed_to_visit"],
        )
