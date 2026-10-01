"""Dialogue session persistence."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

from chatbot.dialogue import Session


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_date(x) -> date | None:
    if x is None:
        return None
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def session_from_row(row) -> Session:
    slots = row["offered_slots"] or []
    if isinstance(slots, str):
        slots = json.loads(slots)
    return Session(
        state=row["state"],
        language=row["language"] or "en",
        patient_id=str(row["patient_id"]) if row["patient_id"] else None,
        appointment_id=str(row["appointment_id"]) if row["appointment_id"] else None,
        offered_slots=[_as_date(s) for s in slots if s],
        pending_date=_as_date(row["pending_date"]),
        visit_date=_as_date(row["visit_date"]),
    )


class MemoryStore:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def get(self, key: str) -> Session | None:
        row = self.rows.get(key)
        return session_from_row(row) if row else None

    def save(self, key: str, session: Session, *, channel: str = "simulator") -> None:
        self.rows[key] = {
            "id": key, "state": session.state, "language": session.language,
            "patient_id": session.patient_id, "appointment_id": session.appointment_id,
            "offered_slots": [d.isoformat() for d in session.offered_slots],
            "pending_date": session.pending_date.isoformat() if session.pending_date else None,
            "visit_date": session.visit_date.isoformat() if session.visit_date else None,
            "channel": channel,
        }


class DbStore:
    def __init__(self, engine):
        self.engine = engine

    def get(self, key: str) -> Session | None:
        from sqlalchemy import text

        with self.engine.connect() as c:
            row = c.execute(text("SELECT * FROM dialogue_sessions WHERE id = :id"), {"id": key}).mappings().first()
        return session_from_row(row) if row else None

    def get_for_patient(self, patient_id: str) -> Session | None:
        from sqlalchemy import text

        with self.engine.connect() as c:
            row = c.execute(
                text("SELECT * FROM dialogue_sessions WHERE patient_id = :p ORDER BY updated_at DESC LIMIT 1"),
                {"p": patient_id},
            ).mappings().first()
        return session_from_row(row) if row else None

    def save(self, key: str, session: Session, *, channel: str = "simulator") -> None:
        from sqlalchemy import text

        now = _now()
        payload = {
            "id": key, "channel": channel, "patient_id": session.patient_id,
            "appointment_id": session.appointment_id, "state": session.state,
            "language": session.language,
            "offered_slots": json.dumps([d.isoformat() for d in session.offered_slots]),
            "pending_date": session.pending_date, "visit_date": session.visit_date,
            "t": now,
        }
        with self.engine.begin() as c:
            exists = c.execute(text("SELECT 1 FROM dialogue_sessions WHERE id = :id"), {"id": key}).scalar()
            if exists:
                c.execute(
                    text(
                        """UPDATE dialogue_sessions SET channel=:channel, patient_id=:patient_id,
                           appointment_id=:appointment_id, state=:state, language=:language,
                           offered_slots=CAST(:offered_slots AS jsonb), pending_date=:pending_date,
                           visit_date=:visit_date, updated_at=:t WHERE id=:id"""
                    ),
                    payload,
                )
            else:
                c.execute(
                    text(
                        """INSERT INTO dialogue_sessions (
                               id, channel, patient_id, appointment_id, state, language,
                               offered_slots, pending_date, visit_date, created_at, updated_at
                           ) VALUES (
                               :id, :channel, :patient_id, :appointment_id, :state, :language,
                               CAST(:offered_slots AS jsonb), :pending_date, :visit_date, :t, :t
                           )"""
                    ),
                    payload,
                )


def new_session_id() -> str:
    return str(uuid.uuid4())
