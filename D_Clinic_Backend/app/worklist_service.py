"""Worklist persistence and call-result recording (Step 3).

Builds today's list for one or all facilities and stores it in ``worklist_items``;
records call outcomes with Simple's exact vocabulary and keeps the appointment
row in sync the way Simple's own app does.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ml.features import build_feature_table, load_tables_from_db
from ml.predict import score_frame
from ml.train import load_artifact
from ml.worklist import WorklistConfig, build_worklist

RESULT_TYPES = {"agreed_to_visit", "remind_to_call_later", "removed_from_overdue_list"}
REMOVE_REASONS = {"not_responding", "moved", "dead", "invalid_phone_number", "public_hospital_transfer",
                  "moved_to_private", "refused_to_return", "other"}
# Simple cancels the appointment on removal and stores the remove reason as the appointment's cancel_reason.
# Patient statuses Simple sets when a removal implies the patient left the program.
PATIENT_STATUS_ON_REMOVE = {"dead": "dead", "moved": "migrated", "public_hospital_transfer": "migrated", "moved_to_private": "migrated"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_and_store(engine: Engine, list_date: date, facility_id: str | None = None,
                    cfg: WorklistConfig | None = None, rebuild: bool = False) -> dict:
    """Build the worklist for ``list_date`` and store it. Returns counts per facility.

    Open items for the day are replaced; items that already have a call result are kept.
    """
    cfg = cfg or WorklistConfig()
    as_of = pd.Timestamp(list_date)
    tables = load_tables_from_db(engine)
    artifact = load_artifact()
    ft = build_feature_table(tables, as_of)
    scores = score_frame(ft.frame, artifact)

    facilities = [facility_id] if facility_id else sorted(tables["appointments"].facility_id.astype(str).unique())
    counts: dict[str, int] = {}
    with engine.begin() as c:
        for fac in facilities:
            existing = c.execute(text("""SELECT count(*) FROM worklist_items
                                         WHERE facility_id = :f AND list_date = :d"""), {"f": fac, "d": list_date}).scalar()
            if existing and not rebuild:
                counts[fac] = -1  # already built, untouched
                continue
            c.execute(text("""DELETE FROM worklist_items WHERE facility_id = :f AND list_date = :d
                              AND call_result_id IS NULL"""), {"f": fac, "d": list_date})
            kept = c.execute(text("""SELECT list_type, appointment_id FROM worklist_items
                                     WHERE facility_id = :f AND list_date = :d"""), {"f": fac, "d": list_date}).all()
            done_appts = {str(a) for _, a in kept}
            # items already actioned today keep their slot: shrink capacity accordingly
            fac_cfg = replace(cfg,
                              capacity=max(cfg.capacity - sum(t == "overdue" for t, _ in kept), 0),
                              pre_visit_slots=max(cfg.pre_visit_slots - sum(t == "pre_visit" for t, _ in kept), 0))
            wl = build_worklist(tables, as_of, artifact, fac_cfg, facility_id=fac, scores=scores)
            wl = wl[wl.selected]
            rows = [{
                "id": str(uuid.uuid4()), "facility_id": fac, "list_date": list_date, "list_type": r.list_type,
                "rank": int(r.rank), "patient_id": str(r.patient_id), "appointment_id": str(r.appointment_id),
                "priority": None if pd.isna(r.priority) else float(r.priority),
                "p_missed": None if pd.isna(r.p_missed) else float(r.p_missed),
                "band": None if pd.isna(r.band) else r.band, "basis": None if pd.isna(r.basis) else r.basis,
                "days_overdue": int(r.days_overdue), "uncontrolled": bool(r.uncontrolled), "protected_slot": bool(r.protected_slot),
                "has_phone": bool(r.has_phone), "suggested_action": r.suggested_action, "reasons": json.dumps(list(r.reasons)),
                "status": "open", "created_at": _now(),
            } for r in wl.itertuples(index=False) if str(r.appointment_id) not in done_appts]
            if rows:
                c.execute(text("""INSERT INTO worklist_items (id, facility_id, list_date, list_type, rank, patient_id, appointment_id,
                                    priority, p_missed, band, basis, days_overdue, uncontrolled, protected_slot, has_phone,
                                    suggested_action, reasons, status, created_at)
                                  VALUES (:id, :facility_id, :list_date, :list_type, :rank, :patient_id, :appointment_id,
                                    :priority, :p_missed, :band, :basis, :days_overdue, :uncontrolled, :protected_slot, :has_phone,
                                    :suggested_action, CAST(:reasons AS jsonb), :status, :created_at)"""), rows)
            counts[fac] = len(rows)
    return counts


def fetch_worklist(engine: Engine, facility_id: str, list_date: date, build_if_missing: bool = True) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(text("""SELECT * FROM worklist_items WHERE facility_id = :f AND list_date = :d
                                 ORDER BY list_type DESC, rank"""), {"f": facility_id, "d": list_date}).mappings().all()
    if not rows and build_if_missing:
        build_and_store(engine, list_date, facility_id)
        return fetch_worklist(engine, facility_id, list_date, build_if_missing=False)
    return [dict(r) for r in rows]


class CallResultError(ValueError):
    pass


def record_call_result(engine: Engine, appointment_id: str, result_type: str, remove_reason: str | None = None,
                       remind_on: date | None = None, user_id: str | None = None, worklist_item_id: str | None = None,
                       called_at: datetime | None = None) -> dict:
    """Insert a call_results row (Simple vocabulary), update the appointment and close the worklist item."""
    if result_type not in RESULT_TYPES:
        raise CallResultError(f"result_type must be one of {sorted(RESULT_TYPES)}")
    if result_type == "removed_from_overdue_list":
        if remove_reason not in REMOVE_REASONS:
            raise CallResultError(f"remove_reason must be one of {sorted(REMOVE_REASONS)}")
    elif remove_reason is not None:
        raise CallResultError("remove_reason only applies to removed_from_overdue_list")
    now = called_at or _now()
    today = now.date()

    with engine.begin() as c:
        appt = c.execute(text("SELECT id, patient_id, facility_id, status FROM appointments WHERE id = :id"),
                         {"id": appointment_id}).mappings().first()
        if not appt:
            raise CallResultError("appointment not found")
        if user_id is None:
            user_id = c.execute(text("""SELECT id FROM users WHERE registration_facility_id = :f ORDER BY created_at LIMIT 1"""),
                                {"f": str(appt["facility_id"])}).scalar()
            if user_id is None:
                raise CallResultError("no user at this facility; pass user_id")
        call_id = str(uuid.uuid4())
        c.execute(text("""INSERT INTO call_results (id, user_id, appointment_id, patient_id, facility_id, result_type, remove_reason,
                                                    device_created_at, device_updated_at)
                          VALUES (:id, :u, :a, :p, :f, :rt, :rr, :t, :t)"""),
                  {"id": call_id, "u": str(user_id), "a": str(appt["id"]), "p": str(appt["patient_id"]), "f": str(appt["facility_id"]),
                   "rt": result_type, "rr": remove_reason, "t": now})

        if result_type == "agreed_to_visit":
            c.execute(text("UPDATE appointments SET agreed_to_visit = true, remind_on = NULL, device_updated_at = :t WHERE id = :a"),
                      {"a": str(appt["id"]), "t": now})
        elif result_type == "remind_to_call_later":
            c.execute(text("UPDATE appointments SET remind_on = :r, device_updated_at = :t WHERE id = :a"),
                      {"a": str(appt["id"]), "r": remind_on or today + timedelta(days=7), "t": now})
        else:
            c.execute(text("""UPDATE appointments SET status = 'cancelled', cancel_reason = :cr, device_updated_at = :t WHERE id = :a"""),
                      {"a": str(appt["id"]), "cr": remove_reason, "t": now})
            new_status = PATIENT_STATUS_ON_REMOVE.get(remove_reason)
            if new_status:
                c.execute(text("UPDATE patients SET status = :s WHERE id = :p"), {"s": new_status, "p": str(appt["patient_id"])})

        params = {"cid": call_id, "a": str(appt["id"])}
        where = "appointment_id = :a AND status = 'open'"
        if worklist_item_id:
            where += " AND id = :wid"
            params["wid"] = worklist_item_id
        closed = c.execute(text(f"UPDATE worklist_items SET status = 'done', call_result_id = :cid WHERE {where}"), params).rowcount
    return {"call_result_id": call_id, "appointment_id": str(appt["id"]), "patient_id": str(appt["patient_id"]),
            "result_type": result_type, "remove_reason": remove_reason, "worklist_items_closed": int(closed)}


def skip_item(engine: Engine, worklist_item_id: str) -> bool:
    with engine.begin() as c:
        return c.execute(text("UPDATE worklist_items SET status = 'skipped' WHERE id = :id AND status = 'open'"),
                         {"id": worklist_item_id}).rowcount == 1
