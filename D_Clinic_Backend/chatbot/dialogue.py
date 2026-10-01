"""Dialogue state machine. The model never chooses a tool or a slot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from chatbot.dates import closed_day_hint, is_clinic_day, match_offered, parse_date_hint
from chatbot.nlu import NluResult, understand_rules
from chatbot.templates import has_unfilled_placeholder, is_unsafe_reply, render, skeleton
from llm.scan import scan_text

STATES = ("idle", "confirming", "choosing_slot", "rescheduling", "cancelling", "handoff")


@dataclass
class Session:
    state: str = "idle"
    language: str = "en"
    patient_id: str | None = None
    appointment_id: str | None = None
    offered_slots: list[date] = field(default_factory=list)
    pending_date: date | None = None
    visit_date: date | None = None


@dataclass
class TurnResult:
    reply: str
    session: Session
    nlu: NluResult
    task_completed: str | None  # confirmed | rescheduled | cancelled | stopped | handed_off
    staff_task: str | None
    unsafe: bool
    pii: bool


def _reply(session: Session, key: str, **fmt) -> str:
    text = render(key, session.language, **fmt)
    if has_unfilled_placeholder(text):
        text = render(key, "en", **fmt)
    return text


def _maybe_rephrase(text: str, lang: str, visit=None, slots=None, extra_date=None) -> str:
    """Optional gateway rephrase; dates are inserted here, never by the model."""
    from app.settings import settings

    if (settings.llm_provider or "none").lower() in {"", "none", "off", "template"}:
        return text
    from llm.gateway import complete

    # Send placeholders, not the filled dates.
    skel = text
    for label, val in (("VISIT", visit), ("DATE1", extra_date or (slots[0] if slots else None)),
                       ("DATE2", slots[1] if slots and len(slots) > 1 else None),
                       ("DATE3", slots[2] if slots and len(slots) > 2 else None)):
        if val is not None:
            from chatbot.dates import format_sms_date
            skel = skel.replace(format_sms_date(val), label)
    gw = complete(f"language={lang}\n\n{skel}", prompt_version="rephrase_v1")
    if not gw.text or is_unsafe_reply(gw.text) or scan_text(gw.text):
        return text
    filled = gw.text
    # Re-insert dates from code.
    from chatbot.dates import format_sms_date
    if visit is not None:
        filled = filled.replace("VISIT", format_sms_date(visit))
    if extra_date is not None:
        filled = filled.replace("DATE1", format_sms_date(extra_date))
    if slots:
        for i, d in enumerate(slots[:3], start=1):
            filled = filled.replace(f"DATE{i}", format_sms_date(d))
    if has_unfilled_placeholder(filled) or is_unsafe_reply(filled) or scan_text(filled):
        return text
    return filled


def _offer_slots(session: Session, tools, as_of: date) -> list[date]:
    skip = session.visit_date
    fac = "fac-1"
    appt = tools.current_appointment(session.patient_id) if session.patient_id else None
    if appt:
        fac = appt.facility_id
        skip = appt.scheduled_date
    slots = tools.get_available_slots(fac, as_of, 3, skip=skip)
    session.offered_slots = slots
    return slots


def start_reminder(session: Session, tools, as_of: date) -> TurnResult:
    appt = tools.current_appointment(session.patient_id) if session.patient_id else None
    if not appt:
        dummy = NluResult("unknown", None, None, None, session.language, True, "rules")
        session.state = "handoff"
        return TurnResult(_reply(session, "no_appointment"), session, dummy, None, "handoff", False, False)
    session.appointment_id = appt.id
    session.visit_date = appt.scheduled_date
    session.state = "confirming"
    dummy = NluResult("unknown", None, None, None, session.language, False, "rules")
    reply = _reply(session, "reminder", visit=appt.scheduled_date)
    return TurnResult(reply, session, dummy, None, None, False, False)


def handle_turn(session: Session, text: str, tools, as_of: date,
                nlu: NluResult | None = None) -> TurnResult:
    nlu = nlu or understand_rules(text, state=session.state)
    session.language = nlu.language or session.language
    completed = None
    staff = None

    appt = None
    if session.patient_id:
        appt = tools.current_appointment(session.patient_id)
        if appt:
            session.appointment_id = appt.id
            session.visit_date = appt.scheduled_date

    # --- safety first: never book from these intents ---
    if nlu.intent == "stop":
        if session.patient_id:
            tools.set_consent(session.patient_id, "denied")
        session.state = "idle"
        reply = _reply(session, "stopped")
        return _finish(session, nlu, reply, "stopped", None)

    if nlu.intent == "symptom_or_medical":
        if session.patient_id:
            tools.create_staff_task(session.patient_id, "medical_callback")
        session.state = "handoff"
        return _finish(session, nlu, _reply(session, "medical"), "handed_off", "medical_callback")

    if nlu.intent == "wrong_number":
        if session.patient_id:
            tools.set_consent(session.patient_id, "denied")
            tools.create_staff_task(session.patient_id, "wrong_number")
        session.state = "handoff"
        return _finish(session, nlu, _reply(session, "wrong_number"), "handed_off", "wrong_number")

    if session.state == "handoff" and nlu.intent not in {"stop"}:
        return _finish(session, nlu, _reply(session, "handoff"), None, None)

    if nlu.needs_human and nlu.intent == "unknown" and session.state == "idle":
        # jailbreak / nonsense: do not book, do not advise
        reply = _reply(session, "unknown", visit=session.visit_date)
        return _finish(session, nlu, reply, None, None)

    if not appt and nlu.intent in {"confirm", "reschedule", "cancel", "ask_slot"}:
        if session.patient_id:
            tools.create_staff_task(session.patient_id, "handoff")
        session.state = "handoff"
        return _finish(session, nlu, _reply(session, "no_appointment"), "handed_off", "handoff")

    # --- confirming a proposed reschedule ---
    if session.state == "rescheduling":
        if nlu.intent == "confirm" and nlu.confirm is False:
            session.state = "idle"
            session.pending_date = None
            return _finish(session, nlu, _reply(session, "kept", visit=session.visit_date), None, None)
        if nlu.intent == "confirm" and session.pending_date and appt:
            new = tools.reschedule(appt.id, session.pending_date)
            session.appointment_id = new.id
            session.visit_date = new.scheduled_date
            session.state = "idle"
            session.pending_date = None
            return _finish(session, nlu, _reply(session, "rescheduled", extra_date=new.scheduled_date),
                           "rescheduled", None)
        if nlu.intent == "ask_slot" or (nlu.intent == "confirm" and nlu.confirm is None):
            nlu = NluResult("ask_slot", nlu.date_hint, None, None, nlu.language, False, nlu.source)

    # --- cancelling ---
    if session.state == "cancelling":
        if nlu.intent == "confirm" and nlu.confirm is False:
            session.state = "idle"
            return _finish(session, nlu, _reply(session, "kept", visit=session.visit_date), None, None)
        if nlu.intent == "confirm" and appt:
            tools.cancel(appt.id)
            session.state = "idle"
            return _finish(session, nlu, _reply(session, "cancelled"), "cancelled", None)
        if nlu.intent == "reschedule":
            pass  # fall through
        elif nlu.intent != "cancel":
            return _finish(session, nlu, _reply(session, "cancel_ask", visit=session.visit_date), None, None)

    # --- choosing a numbered slot ---
    if session.state == "choosing_slot":
        chosen = match_offered(text, nlu.date_hint, as_of, session.offered_slots)
        if chosen and appt and nlu.intent not in {"cancel", "stop", "symptom_or_medical", "wrong_number"}:
            if not is_clinic_day(chosen):
                slots = _offer_slots(session, tools, as_of)
                session.state = "choosing_slot"
                return _finish(session, nlu, _reply(session, "closed_day", slots=slots), None, None)
            new = tools.reschedule(appt.id, chosen)
            session.appointment_id = new.id
            session.visit_date = new.scheduled_date
            session.state = "idle"
            session.offered_slots = []
            return _finish(session, nlu, _reply(session, "rescheduled", extra_date=new.scheduled_date),
                           "rescheduled", None)
        if closed_day_hint(nlu.date_hint) or closed_day_hint(text):
            slots = session.offered_slots or _offer_slots(session, tools, as_of)
            return _finish(session, nlu, _reply(session, "closed_day", slots=slots), None, None)
        slots = session.offered_slots or _offer_slots(session, tools, as_of)
        session.offered_slots = slots
        return _finish(session, nlu, _reply(session, "slots", slots=slots), None, None)

    # --- new intents from idle / confirming / leftover ---
    if nlu.intent == "confirm" and appt:
        tools.book(appt.id)
        session.state = "idle"
        return _finish(session, nlu, _reply(session, "confirmed", visit=appt.scheduled_date), "confirmed", None)

    if nlu.intent == "cancel" and appt:
        session.state = "cancelling"
        return _finish(session, nlu, _reply(session, "cancel_ask", visit=appt.scheduled_date), None, None)

    if nlu.intent in {"reschedule", "ask_slot"} and appt:
        hint_date = parse_date_hint(nlu.date_hint, as_of, session.offered_slots)
        slots = _offer_slots(session, tools, as_of)
        if closed_day_hint(nlu.date_hint) or (hint_date and not is_clinic_day(hint_date)):
            session.state = "choosing_slot"
            return _finish(session, nlu, _reply(session, "closed_day", slots=slots), None, None)
        if hint_date and hint_date in slots:
            session.pending_date = hint_date
            session.state = "rescheduling"
            return _finish(session, nlu, _reply(session, "reschedule_ask", extra_date=hint_date, slots=slots),
                           None, None)
        session.state = "choosing_slot"
        return _finish(session, nlu, _reply(session, "slots", slots=slots), None, None)

    reply = _reply(session, "unknown", visit=session.visit_date)
    return _finish(session, nlu, reply, completed, staff)


def _finish(session: Session, nlu: NluResult, reply: str, completed: str | None,
            staff: str | None) -> TurnResult:
    reply = _maybe_rephrase(
        reply, session.language, visit=session.visit_date,
        slots=session.offered_slots or None, extra_date=session.pending_date,
    )
    pii = bool(scan_text(reply))
    unsafe = is_unsafe_reply(reply) or pii
    if unsafe:
        # Last-resort safe line — never ship a leaked or clinical reply.
        reply = skeleton("handoff", session.language)
        pii = bool(scan_text(reply))
        unsafe = is_unsafe_reply(reply) or pii
    return TurnResult(reply, session, nlu, completed, staff, unsafe, pii)
