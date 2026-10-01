"""FastAPI application.

Step 2 exposes health and risk-scoring endpoints; Step 3 adds the daily worklist
and call-result recording; Step 4 adds the de-identified patient summary.
Step 5 adds the SMS scheduling chatbot; Step 6 adds the protocol ready-reckoner. Nothing here returns names,
phone numbers or addresses.
"""

from __future__ import annotations

from datetime import date, datetime
import json
import re

import pandas as pd
from fastapi import FastAPI, Form, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db import engine
from app.metrics import Timer, inc, render_prometheus
from app.settings import REPO_ROOT
from ml.predict import score_upcoming, write_scores

app = FastAPI(title="Followup-AI", version="0.10.0",
              description="AI follow-up layer for a hypertension/diabetes program (Simple-compatible).")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:8010",
        "http://127.0.0.1:8010",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}


def _score_band_metrics() -> list[str]:
    try:
        with engine.connect() as c:
            rows = c.execute(
                text("SELECT band, count(*) FROM latest_risk_scores GROUP BY band")
            ).all()
    except Exception:
        return []
    lines = [
        "# HELP followup_risk_scores Latest risk scores by band",
        "# TYPE followup_risk_scores gauge",
    ]
    for band, n in rows:
        lines.append(f'followup_risk_scores{{band="{band}"}} {int(n)}')
    return lines


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus text. Process counters plus latest score-band counts when the DB is up."""
    return Response(
        render_prometheus(_score_band_metrics()),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


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
    last_interaction: str | None = None
    last_interaction_at: datetime | None = None


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
                           call_result_id=None if r["call_result_id"] is None else str(r["call_result_id"]),
                           last_interaction=r.get("last_interaction"),
                           last_interaction_at=r.get("last_interaction_at"))


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
        from app.audit import write_event

        write_event(
            engine, action="worklist.rebuilt", subject_type="worklist",
            subject_id=f"{facility_id}:{list_date.isoformat()}", facility_id=facility_id,
            extra={"list_date": list_date.isoformat()},
        )
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
        with Timer():
            res = record_call_result(engine, **body.model_dump())
    except CallResultError as e:
        raise HTTPException(422, str(e))
    from app.audit import write_event

    write_event(
        engine, action="call_result.recorded", actor_id=body.user_id,
        subject_type="appointment", subject_id=res["appointment_id"],
        extra={"result_type": res["result_type"], "call_result_id": res["call_result_id"]},
    )
    inc("followup_call_results_total")
    return CallResultOut(**res)


@app.post("/worklist/items/{item_id}/skip", status_code=204)
def skip_worklist_item(item_id: str) -> None:
    from app.worklist_service import skip_item

    if not skip_item(engine, item_id):
        raise HTTPException(404, "open worklist item not found")
    from app.audit import write_event

    write_event(engine, action="worklist.skipped", subject_type="worklist_item", subject_id=item_id)


# ------------------------------------------------------------------------------- summary


class SummaryIn(BaseModel):
    as_of: date | None = Field(default=None, description="Clinical as-of date; defaults to today")
    persist: bool = Field(default=True, description="Write an llm_requests audit row")


class SummaryOut(BaseModel):
    patient_id: str
    case_code: str
    facts: dict
    summary: str
    source: str
    check: str
    provider: str
    model: str | None
    prompt_version: str
    model_version: str
    fallback_used: bool
    packet_hash: str


@app.post("/patients/{patient_id}/summary", response_model=SummaryOut)
def patient_summary(patient_id: str, body: SummaryIn | None = None) -> SummaryOut:
    """Five-line briefing from structured data. Identity never enters the prompt."""
    from llm.deid import DeidError
    from llm.summary import summarize_patient

    req = body or SummaryIn()
    from app.audit import write_event

    try:
        with Timer():
            result = summarize_patient(engine, patient_id, as_of=req.as_of, persist=req.persist)
    except KeyError:
        raise HTTPException(404, "patient not found")
    except DeidError as exc:
        inc("followup_pii_refusals_total")
        write_event(
            engine, action="summary.refused", subject_type="patient", subject_id=patient_id,
            extra={"reason": "deid"},
        )
        raise HTTPException(422, str(exc))
    inc("followup_summaries_total")
    if result.fallback_used or result.check != "passed":
        inc("followup_check_failures_total")
    write_event(
        engine, action="summary.viewed", subject_type="patient", subject_id=patient_id,
        extra={"case_code": result.case_code, "source": result.source, "check": result.check,
               "prompt_version": result.prompt_version, "model_version": result.model or "template"},
    )
    return SummaryOut(**result.as_api(patient_id))


# ------------------------------------------------------------------------------- sms chatbot


class SmsIn(BaseModel):
    body: str
    patient_id: str | None = None
    sender: str | None = Field(default=None, description="Phone; resolved server-side, never sent to a model")
    as_of: date | None = None
    session_id: str | None = None


class SmsOut(BaseModel):
    reply: str
    session_id: str
    state: str
    intent: str
    language: str
    task_completed: str | None
    staff_task: str | None
    patient_id: str | None
    nlu_source: str


class ReminderIn(BaseModel):
    patient_id: str
    as_of: date | None = None


def _sms_result(res) -> SmsOut:
    return SmsOut(
        reply=res.reply, session_id=res.session_id, state=res.state, intent=res.intent,
        language=res.language, task_completed=res.task_completed, staff_task=res.staff_task,
        patient_id=res.patient_id, nlu_source=res.nlu_source,
    )


@app.post("/sms/inbound", response_model=SmsOut)
def sms_inbound(body: SmsIn) -> SmsOut:
    """In-app SMS simulator. Identity is resolved here; the model sees only the redacted line."""
    from chatbot.service import api_tools_store, process_inbound

    as_of = body.as_of or date.today()
    tools, store = api_tools_store(engine, as_of)
    with Timer():
        res = process_inbound(
            text=body.body, tools=tools, store=store, as_of=as_of,
            patient_id=body.patient_id, phone=body.sender, channel="simulator",
            session_id=body.session_id, nlu_prefer="auto",
        )
    if res.staff_task:
        inc("followup_unsafe_intents_total")
    return _sms_result(res)


@app.post("/sms/outbound", response_model=SmsOut)
def sms_outbound(body: ReminderIn) -> SmsOut:
    """Start a reminder thread (puts the session in confirming)."""
    from chatbot.service import api_tools_store, process_reminder

    as_of = body.as_of or date.today()
    tools, store = api_tools_store(engine, as_of)
    return _sms_result(process_reminder(tools=tools, store=store, as_of=as_of, patient_id=body.patient_id))


@app.post("/sms/webhook")
def sms_webhook(
    from_: str = Form(default="", alias="from"),
    to: str = Form(default=""),
    text: str = Form(default=""),
    date_str: str = Form(default="", alias="date"),
    id: str = Form(default=""),
) -> dict:
    """Africa's Talking sandbox inbox shape (application/x-www-form-urlencoded)."""
    from chatbot.service import api_tools_store, process_inbound

    as_of = date.today()
    tools, store = api_tools_store(engine, as_of)
    res = process_inbound(
        text=text, tools=tools, store=store, as_of=as_of, phone=from_, channel="africastalking",
        nlu_prefer="auto",
    )
    return {"reply": res.reply, "session_id": res.session_id, "to": to, "id": id}


@app.get("/sms/threads/{patient_id}")
def sms_thread(patient_id: str, limit: int = Query(default=50, le=200)) -> dict:
    """Staff view of a simulated thread. Phone numbers are not returned."""
    with engine.connect() as c:
        rows = c.execute(
            text(
                """SELECT direction, body, language, communication_type, device_created_at
                   FROM communications WHERE patient_id = :p
                   ORDER BY device_created_at DESC LIMIT :n"""
            ),
            {"p": patient_id, "n": limit},
        ).mappings().all()
        tasks = c.execute(
            text("SELECT id, kind, status, created_at FROM staff_tasks WHERE patient_id = :p ORDER BY created_at DESC"),
            {"p": patient_id},
        ).mappings().all()
        calls = c.execute(
            text(
                """SELECT result_type, remove_reason, device_created_at
                   FROM call_results WHERE patient_id = :p
                   ORDER BY device_created_at DESC LIMIT :n"""
            ),
            {"p": patient_id, "n": limit},
        ).mappings().all()
    return {
        "patient_id": patient_id,
        "messages": [
            {
                "direction": r["direction"], "body": r["body"], "language": r["language"],
                "communication_type": r["communication_type"],
                "at": r["device_created_at"].isoformat() if r["device_created_at"] else None,
            }
            for r in reversed(list(rows))
        ],
        "calls": [
            {
                "result_type": r["result_type"],
                "remove_reason": r["remove_reason"],
                "at": r["device_created_at"].isoformat() if r["device_created_at"] else None,
            }
            for r in calls
        ],
        "staff_tasks": [
            {
                "id": str(t["id"]), "kind": t["kind"], "status": t["status"],
                "at": t["created_at"].isoformat() if t["created_at"] else None,
            }
            for t in tasks
        ],
    }


# ------------------------------------------------------------------------------- ready-reckoner


class ReckonerAskIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


class ReckonerAskOut(BaseModel):
    question: str
    answer: str
    refused: bool
    covered: bool
    citations: list[dict]
    source: str
    check: str
    fallback_used: bool


class NextStepIn(BaseModel):
    systolic: int | None = None
    diastolic: int | None = None
    drugs: list[dict] = Field(default_factory=list, description="[{name, dosage}] from the record, not the model")


@app.post("/reckoner/ask", response_model=ReckonerAskOut)
def reckoner_ask(body: ReckonerAskIn) -> ReckonerAskOut:
    """Protocol Q&A from HEARTS / PHC chunks. Refuses when not covered. Not a prescription."""
    from reckoner.ask import ask

    with Timer():
        result = ask(body.question)
    if result.check not in {"passed", "ok", ""} and not result.refused:
        inc("followup_check_failures_total")
    elif getattr(result, "fallback_used", False):
        inc("followup_check_failures_total")
    return ReckonerAskOut(**result.as_api())


@app.post("/reckoner/next-step")
def reckoner_next_step(body: NextStepIn) -> dict:
    """Deterministic HEARTS next step from BP and current protocol drugs."""
    from reckoner.next_step import next_step

    ns = next_step(body.systolic, body.diastolic, body.drugs)
    return {
        "controlled": ns.controlled, "current_step": ns.current_step, "action": ns.action,
        "guidance": ns.guidance, "cite": ns.cite, "next_regimen": ns.next_regimen,
    }


def _row(r) -> RiskRow:
    return RiskRow(appointment_id=str(r["appointment_id"]), patient_id=str(r["patient_id"]), facility_id=str(r["facility_id"]),
                   scheduled_date=r["scheduled_date"], p_missed=float(r["p_missed"]), band=r["band"], basis=r["basis"],
                   group_size=int(r["group_size"]), group_level=r["group_level"], reasons=list(r["reasons"] or []),
                   model_version=r["model_version"])


# ------------------------------------------------------------------------------- frontend demo (Step 10)


class FeedbackIn(BaseModel):
    case_code: str | None = None
    verdict: str = Field(..., description="useful | missing_fact | wrong_number | other")


EVAL_REPORTS = (
    ("worklist", "Worklist replay"),
    ("missed_visit_model", "Missed-visit model"),
    ("summary", "Worker summaries"),
    ("chatbot", "SMS chatbot"),
    ("reckoner", "Ready-reckoner"),
    ("drift", "Weekly drift"),
)

_HEADLINE = re.compile(r"(?ms)^## Headline\s+(.*?)(?:\n## |\Z)")


def _report_payload(slug: str, title: str) -> dict:
    path = REPO_ROOT / "docs" / "eval_reports" / f"{slug}.md"
    if not path.exists():
        raise HTTPException(404, f"report {slug} not found")
    body = path.read_text(encoding="utf-8")
    m = _HEADLINE.search(body)
    headline = " ".join((m.group(1) if m else body.split("\n", 3)[-1]).split())
    return {"id": slug, "title": title, "headline": headline[:400], "body": body}


@app.get("/facilities")
def list_facilities() -> list[dict]:
    """Clinic picker. Facility names only — no patient identity."""
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT id, name, facility_type, district FROM facilities ORDER BY name")
        ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "facility_type": r["facility_type"],
            "district": r["district"],
        }
        for r in rows
    ]


@app.get("/demo/context")
def demo_context() -> dict:
    """Defaults that make the four screens work on the seeded synthetic cohort."""
    worklist_as_of = date(2026, 9, 22)
    sms_as_of = date(2026, 9, 26)
    with engine.connect() as c:
        facilities = [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "facility_type": r["facility_type"],
                "district": r["district"],
            }
            for r in c.execute(
                text("SELECT id, name, facility_type, district FROM facilities ORDER BY name")
            ).mappings().all()
        ]
        chat = c.execute(
            text(
                """SELECT p.id::text
                   FROM patients p
                   JOIN appointments a ON a.patient_id = p.id AND a.status = 'scheduled'
                        AND a.scheduled_date >= :d
                   WHERE p.reminder_consent = 'granted' AND p.deleted_at IS NULL
                   ORDER BY a.scheduled_date
                   LIMIT 1"""
            ),
            {"d": sms_as_of},
        ).scalar()
    return {
        "worklist_as_of": worklist_as_of.isoformat(),
        "sms_as_of": sms_as_of.isoformat(),
        "facilities": facilities,
        "chat_patient_id": chat,
    }


@app.get("/eval/reports")
def eval_reports() -> list[dict]:
    out = []
    for slug, title in EVAL_REPORTS:
        path = REPO_ROOT / "docs" / "eval_reports" / f"{slug}.md"
        if path.exists():
            row = _report_payload(slug, title)
            row.pop("body")
            out.append(row)
    return out


@app.get("/eval/reports/{slug}")
def eval_report(slug: str) -> dict:
    title = dict(EVAL_REPORTS).get(slug)
    if not title:
        raise HTTPException(404, "unknown report")
    return _report_payload(slug, title)


@app.get("/eval/registry")
def eval_registry() -> dict:
    path = REPO_ROOT / "D_Clinic_Backend" / "ml" / "registry" / "registry.json"
    if not path.exists():
        raise HTTPException(404, "registry missing")
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_feedback(patient_id: str) -> dict:
    with engine.connect() as c:
        row = c.execute(
            text(
                """SELECT extra->>'verdict' AS verdict, extra->>'case_code' AS case_code, created_at
                   FROM audit_events
                   WHERE action = 'summary.feedback' AND subject_id = :p
                   ORDER BY created_at DESC LIMIT 1"""
            ),
            {"p": patient_id},
        ).mappings().first()
    if not row or not row["verdict"]:
        return {"verdict": None, "case_code": None, "rated_at": None}
    at = row["created_at"]
    return {
        "verdict": row["verdict"],
        "case_code": row["case_code"],
        "rated_at": at.isoformat() if at is not None else None,
    }


@app.get("/patients/{patient_id}/feedback")
def latest_summary_feedback(patient_id: str) -> dict:
    """Last staff rating for this briefing. Append-only; does not change the record."""
    return _latest_feedback(patient_id)


@app.post("/patients/{patient_id}/feedback", status_code=201)
def summary_feedback(patient_id: str, body: FeedbackIn) -> dict:
    """Worker rating of a briefing. Verdict is an enum; no free text (identity risk)."""
    allowed = {"useful", "missing_fact", "wrong_number", "other"}
    if body.verdict not in allowed:
        raise HTTPException(422, f"verdict must be one of {sorted(allowed)}")
    from app.audit import write_event

    write_event(
        engine,
        action="summary.feedback",
        subject_type="patient",
        subject_id=patient_id,
        extra={"verdict": body.verdict, "case_code": body.case_code},
    )
    return _latest_feedback(patient_id)
