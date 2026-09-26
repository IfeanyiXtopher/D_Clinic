"""FastAPI application.

Step 2 exposes health and risk-scoring endpoints. Later steps add the worklist,
summaries, chatbot webhook and ready-reckoner. Nothing here returns names,
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

app = FastAPI(title="Followup-AI", version="0.2.0",
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


def _row(r) -> RiskRow:
    return RiskRow(appointment_id=str(r["appointment_id"]), patient_id=str(r["patient_id"]), facility_id=str(r["facility_id"]),
                   scheduled_date=r["scheduled_date"], p_missed=float(r["p_missed"]), band=r["band"], basis=r["basis"],
                   group_size=int(r["group_size"]), group_level=r["group_level"], reasons=list(r["reasons"] or []),
                   model_version=r["model_version"])
