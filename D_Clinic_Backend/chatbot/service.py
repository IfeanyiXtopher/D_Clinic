"""Glue: resolve identity, run the state machine, persist, never put a phone in NLU."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from chatbot.dialogue import Session, TurnResult, handle_turn, start_reminder
from chatbot.nlu import understand, understand_rules
from chatbot.store import DbStore, MemoryStore, new_session_id
from chatbot.tools import DbTools, MemoryTools, hash_phone


@dataclass
class InboundResult:
    reply: str
    session_id: str
    state: str
    intent: str
    language: str
    task_completed: str | None
    staff_task: str | None
    patient_id: str | None
    nlu_source: str


def _nlu(text: str, state: str, prefer: str, offered=None):
    if prefer == "classifier":
        from chatbot.classifier import predict_intent
        from chatbot.nlu import NluResult, detect_language

        rules = understand_rules(text, state=state)
        intent = predict_intent(text)
        return NluResult(intent, rules.date_hint, None, rules.confirm, detect_language(text),
                         intent in {"symptom_or_medical", "wrong_number"}, "classifier")
    if prefer in {"llm", "auto"}:
        return understand(text, state=state, prefer=prefer, offered=offered)
    return understand_rules(text, state=state)


def process_inbound(*, text: str, tools, store, as_of: date,
                    patient_id: str | None = None, phone: str | None = None,
                    channel: str = "simulator", nlu_prefer: str = "rules",
                    session_id: str | None = None) -> InboundResult:
    if phone and not patient_id and hasattr(tools, "resolve_phone"):
        patient_id = tools.resolve_phone(phone)

    key = session_id or (f"p:{patient_id}" if patient_id else f"h:{hash_phone(phone or new_session_id())}")
    session = store.get(key) or Session(patient_id=patient_id)
    session.patient_id = patient_id or session.patient_id

    if not session.patient_id:
        from chatbot.templates import render

        nlu = understand_rules(text, state="idle")
        reply = render("not_on_register", nlu.language)
        return InboundResult(reply, key, "idle", nlu.intent, nlu.language, None, None, None, nlu.source)

    nlu = _nlu(text, session.state, nlu_prefer, offered=session.offered_slots)
    result: TurnResult = handle_turn(session, text, tools, as_of, nlu=nlu)
    store.save(key, result.session, channel=channel)
    tools.record_reply(result.session.patient_id, text, direction="inbound",
                       appointment_id=result.session.appointment_id, language=result.nlu.language)
    tools.record_reply(result.session.patient_id, result.reply, direction="outbound",
                       appointment_id=result.session.appointment_id, language=result.session.language)
    return InboundResult(
        reply=result.reply, session_id=key, state=result.session.state,
        intent=result.nlu.intent, language=result.session.language,
        task_completed=result.task_completed, staff_task=result.staff_task,
        patient_id=result.session.patient_id, nlu_source=result.nlu.source,
    )


def process_reminder(*, tools, store, as_of: date, patient_id: str,
                     channel: str = "simulator") -> InboundResult:
    key = f"p:{patient_id}"
    session = store.get(key) or Session(patient_id=patient_id)
    session.patient_id = patient_id
    result = start_reminder(session, tools, as_of)
    store.save(key, result.session, channel=channel)
    tools.record_reply(patient_id, result.reply, direction="outbound",
                       appointment_id=result.session.appointment_id, language=session.language,
                       communication_type="appointment_reminder")
    return InboundResult(
        reply=result.reply, session_id=key, state=result.session.state,
        intent="reminder", language=session.language, task_completed=None, staff_task=None,
        patient_id=patient_id, nlu_source="rules",
    )


def api_tools_store(engine, as_of: date):
    return DbTools(engine, as_of=as_of), DbStore(engine)


# re-export for tests that want a self-contained loop
MemoryTools = MemoryTools
MemoryStore = MemoryStore
