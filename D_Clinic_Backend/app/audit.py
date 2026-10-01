"""Append-only audit events. Extra must never hold identity fields."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

FORBIDDEN_EXTRA = {
    "full_name", "name", "phone", "phone_number", "number", "nin",
    "street_address", "address", "date_of_birth", "body",
}


class AuditError(ValueError):
    """Refused because the extra payload looked like identity."""


def write_event(
    engine: Engine,
    *,
    action: str,
    actor_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    facility_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    payload = dict(extra or {})
    hit = set(payload) & FORBIDDEN_EXTRA
    if hit:
        raise AuditError(f"refused: identity key in audit extra ({sorted(hit)})")
    event_id = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(
            text(
                """INSERT INTO audit_events
                   (id, action, actor_id, subject_type, subject_id, facility_id, extra, created_at)
                   VALUES (:id, :action, :actor_id, :subject_type, :subject_id, :facility_id,
                           CAST(:extra AS jsonb), :created_at)"""
            ),
            {
                "id": event_id,
                "action": action,
                "actor_id": actor_id,
                "subject_type": subject_type,
                "subject_id": str(subject_id) if subject_id is not None else None,
                "facility_id": facility_id,
                "extra": json.dumps(payload),
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
            },
        )
    return event_id
