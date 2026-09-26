"""FastAPI application.

Step 2 exposes health and risk-scoring endpoints; Step 3 adds the daily worklist
and call-result recording. Later steps add summaries, chatbot webhook and ready-reckoner. Nothing here returns names,
phone numbers or addresses.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db import engine
from ml.predict import score_upcoming, write_scores

app = FastAPI(title="Followup-AI", version="0.3.0",
              description="AI follow-up layer for a hypertension/diabetes program (Simple-compatible).")


@app.get("/health")
def health() -> dict:
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}


# ------------------------------------------------------------------------------- risk


class ScoreRequest(BaseModel):
    appointment_ids: list[str] | None = Field(default=None, description="Score these appointments only")
    facility_id: str | None = Field(default=None, description="Restrict to one facility")
    horizon_days: int = Field(default=60, ge=1, le=365, description="Upcoming window when no ids are given")
    as_of: date | None = Field(default=None, description="Scoring date; defaults to today")
    persist: bool = Field(default=True, description="Write rows to risk_scores")


class RiskRow(BaseModel):
    appointment_id: str
    patient_id: str
    facility_id: str
    scheduled_date: date
    p_missed: float
    band: str
    basis: str
    group_size: int
    group_level: str | None
    reasons: list[str]
    model_version: str


@app.post("/risk/score", response_model=list[RiskRow])
def risk_score(req: ScoreRequest) -> list[RiskRow]:
    scores = score_upcoming(engine, as_of=pd.Timestamp(req.as_of) if req.as_of else None,
                            appointment_ids=req.appointment_ids, facility_id=req.facility_id,
                            horizon_days=req.horizon_days)
    if scores.empty:
        return []
    if req.persist:
        write_scores(scores, engine)
    return [RiskRow(**{**r, "appointment_id": str(r["appointment_id"]), "patient_id": str(r["patient_id"]),
                       "facility_id": str(r["facility_id"]), "reasons": list(r["reasons"])})
            for r in scores.to_dict("records")]


@app.get("/risk/appointments/{appointment_id}", response_model=RiskRow)
def risk_for_appointment(appointment_id: str) -> RiskRow:
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM latest_risk_scores WHERE appointment_id = :id"), {"id": appointment_id}).mappings().first()
    if not row:
        raise HTTPException(404, "no score for this appointment")
    return _row(row)


@app.get("/risk/patients/{patient_id}", response_model=list[RiskRow])
def risk_for_patient(patient_id: str, limit: int = Query(default=10, le=100)) -> list[RiskRow]:
    with engine.connect() as c:
        rows = c.execute(text("""SELECT * FROM latest_risk_scores WHERE patient_id = :id
                                 ORDER BY scheduled_date DESC LIMIT :limit"""), {"id": patient_id, "limit": limit}).mappings().all()
    return [_row(r) for r in rows]


# ------------------------------------------------------------------------------- worklist


class WorklistItemOut(BaseModel):
    id: str
    list_type: str
    rank: int
    patient_id: str
    appointment_id: str
    days_overdue: int
    p_missed: float | None
    band: str | None
    basis: str | None
    uncontrolled: bool
    protected_slot: bool
    has_phone: bool
    suggested_action: str
    reasons: list[str]
    status: str
    call_result_id: str | None


class WorklistOut(BaseModel):
    facility_id: str
    list_date: date
    overdue: list[WorklistItemOut]
    pre_visit: list[WorklistItemOut]
    counts: dict[str, int]


def _item(r: dict) -> WorklistItemOut:
    return WorklistItemOut(id=str(r["id"]), list_type=r["list_type"], rank=int(r["rank"]), patient_id=str(r["patient_id"]),
                           appointment_id=str(r["appointment_id"]), days_overdue=int(r["days_overdue"]),
                           p_missed=None if r["p_missed"] is None else float(r["p_missed"]), band=r["band"], basis=r["basis"],
                           uncontrolled=bool(r["uncontrolled"]), protected_slot=bool(r["protected_slot"]), has_phone=bool(r["has_phone"]),
                           suggested_action=r["suggested_action"], reasons=list(r["reasons"] or []), status=r["status"],
                           call_result_id=None if r["call_result_id"] is None else str(r["call_result_id"]))


@app.get("/worklist", response_model=WorklistOut)
def get_worklist(facility_id: str = Query(..., description="Facility UUID"),
                 list_date: date | None = Query(default=None, alias="date", description="Defaults to today"),
                 rebuild: bool = Query(default=False, description="Rebuild open items for this day")) -> WorklistOut:
    """Today's prioritised follow-up list for a facility. Identity fields are never returned here;
    the app resolves patient_id to contact details on its own side of the privacy boundary."""
    from app.worklist_service import build_and_store, fetch_worklist

    list_date = list_date or date.today()
    if rebuild:
        build_and_store(engine, list_date, facility_id, rebuild=True)
    items = fetch_worklist(engine, facility_id, list_date)
    out = [_item(r) for r in items]
    return WorklistOut(facility_id=facility_id, list_date=list_date,
                       overdue=[i for i in out if i.list_type == "overdue"], pre_visit=[i for i in out if i.list_type == "pre_visit"],
                       counts={"total": len(out), "open": sum(i.status == "open" for i in out),
                               "done": sum(i.status == "done" for i in out), "skipped": sum(i.status == "skipped" for i in out)})


class CallResultIn(BaseModel):
    appointment_id: str
    result_type: str = Field(..., description="agreed_to_visit | remind_to_call_later | removed_from_overdue_list")
    remove_reason: str | None = Field(default=None, description="Required when removed_from_overdue_list (Simple values)")
    remind_on: date | None = Field(default=None, description="For remind_to_call_later; defaults to +7 days")
    user_id: str | None = Field(default=None, description="Health worker; defaults to a user at the facility")
    worklist_item_id: str | None = None


class CallResultOut(BaseModel):
    call_result_id: str
    appointment_id: str
    patient_id: str
    result_type: str
    remove_reason: str | None
    worklist_items_closed: int


@app.post("/call-results", response_model=CallResultOut, status_code=201)
def post_call_result(body: CallResultIn) -> CallResultOut:
    """Record the outcome of a call with Simple's exact vocabulary and keep the appointment in sync."""
    from app.worklist_service import CallResultError, record_call_result

    try:
        res = record_call_result(engine, **body.model_dump())
    except CallResultError as e:
        raise HTTPException(422, str(e))
    return CallResultOut(**res)


@app.post("/worklist/items/{item_id}/skip", status_code=204)
def skip_worklist_item(item_id: str) -> None:
    from app.worklist_service import skip_item

    if not skip_item(engine, item_id):
        raise HTTPException(404, "open worklist item not found")


def _row(r) -> RiskRow:
    return RiskRow(appointment_id=str(r["appointment_id"]), patient_id=str(r["patient_id"]), facility_id=str(r["facility_id"]),
                   scheduled_date=r["scheduled_date"], p_missed=float(r["p_missed"]), band=r["band"], basis=r["basis"],
                   group_size=int(r["group_size"]), group_level=r["group_level"], reasons=list(r["reasons"] or []),
                   model_version=r["model_version"])
