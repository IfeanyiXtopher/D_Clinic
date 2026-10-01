"""Understand an inbound SMS. Rules always run; LLM JSON is optional via the gateway."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from llm.scan import scan_text

INTENTS = (
    "confirm", "reschedule", "cancel", "ask_slot", "stop",
    "symptom_or_medical", "wrong_number", "unknown",
)
LANGS = ("en", "pcm", "ha", "yo")

_JAILBREAK = re.compile(
    r"ignore (all )?(previous|prior|above)|you are now|system prompt|pretend to be|reveal the",
    re.I,
)
_PHONE = re.compile(r"(?:\+?234|\b0[789]\d{2})\s?\d{3}\s?\d{4}")

# Phrase lists are matched as substrings on a folded line (order matters: stop/medical first).
_STOP = (
    "stop sending", "remove my number", "no dey send", "daina aiko", "ma fi ran", "unsubscribe",
)
_MEDICAL = (
    "paining", "pain", "swelling", "swell", "dizzy", "chest", "drugs finish", "drug don finish",
    "finished my drugs", "stop the tablet", "stop the tablets", "feel fine now", "bp is high",
    "body dey weak", "wetin i go do", "ciwon kai", "magani ya kare", "ori n fo", "oogun mi ti tan",
    "prescribe", "dose", "insulin", "can i stop",
)
_WRONG = (
    "wrong number", "who is this", "don't know this person", "do not know this person",
    "i no know this person", "lambar ba tawa", "nomba yi ko",
)
_CANCEL = (
    "cancel", "don't book", "do not book", "i won't come at all", "i will not come at all",
    "i don travel", "i have moved", "no need for appointment",
)
_RESCHEDULE = (
    "reschedule", "change my appointment", "change appointment", "can't come", "cant come",
    "cannot come", "i no fit come", "shift am", "make i come next", "next week instead",
    "ba zan iya zuwa", "mi o le wa", "shift",
)
_ASK = (
    "which day", "what time", "clinic open", "is saturday", "wetin time", "which day i fit",
    "wace rana", "ojo wo",
)
_CONFIRM = (
    "i will come", "i go come", "i dey come", "i go show", "zan zo", "mo ma wa",
    "alright see you", "noted", "na ok", "no wahala", "to, zan", "o da, ma wa",
    "i want to book", "want to book", "book me", "book an appointment",
    "please book", "i want to come",
)
_ACCEPT_SLOT = (
    "okay for me", "ok for me", "is okay", "is good", "is fine",
    "works for me", "that day", "that date", "go with",
)
_ORDINAL = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b", re.I)

_WEEKDAY = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b",
    re.I,
)
_NEXT_WEEK = re.compile(r"next week|mako mai zuwa|ose to n bo|nxt week", re.I)
_TOMORROW = re.compile(r"\b(tomorrow|tomorow|gobe|ola)\b", re.I)
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_SLOT = re.compile(r"^\s*([123])\s*$")


@dataclass
class NluResult:
    intent: str
    date_hint: str | None
    time_hint: str | None
    confirm: bool | None
    language: str
    needs_human: bool
    source: str

    def as_dict(self) -> dict:
        return {
            "intent": self.intent, "date_hint": self.date_hint, "time_hint": self.time_hint,
            "confirm": self.confirm, "language": self.language, "needs_human": self.needs_human,
            "source": self.source,
        }


def redact_for_model(text: str) -> str:
    """Strip phones (and honorific+name) before any model sees the line."""
    out = _PHONE.sub("[PHONE]", text)
    out = re.sub(r"\b(?:Mr|Mrs|Ms|Dr|Alhaji|Alhaja)\.?\s+[A-Z][A-Za-z'-]+", "[NAME]", out)
    return out


def detect_language(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("i go ", "i dey ", "no wahala", "abeg", "wetin", "i no fit", "make i come")):
        return "pcm"
    if any(w in t for w in ("zan zo", "na gode", "ba zan", "wace rana", "daina", "ina jin", "wannan")):
        return "ha"
    if any(w in t for w in ("mo ma wa", "mi o le", "ojo wo", "oogun", "ori n fo", "e ma fi")):
        return "yo"
    return "en"


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    for p in phrases:
        if len(p) <= 3:
            if re.search(rf"\b{re.escape(p)}\b", text):
                return True
        elif p in text:
            return True
    return False


def _date_hint(text: str, state: str) -> str | None:
    if m := _SLOT.match(text.strip()):
        if state in {"confirming", "choosing_slot", "rescheduling", "idle"}:
            return f"slot:{m.group(1)}" if state == "choosing_slot" else (
                m.group(1) if state == "choosing_slot" else None
            )
        if state == "choosing_slot":
            return f"slot:{m.group(1)}"
    if state == "choosing_slot" and text.strip() in {"1", "2", "3"}:
        return f"slot:{text.strip()}"
    if m := _ISO.search(text):
        return m.group(1)
    if _NEXT_WEEK.search(text):
        return "next_week"
    if _TOMORROW.search(text):
        return "tomorrow"
    if m := _WEEKDAY.search(text):
        return m.group(1).lower()
    if m := _ORDINAL.search(text):
        return m.group(0).lower()
    return None


def understand_rules(text: str, *, state: str = "idle") -> NluResult:
    raw = text.strip()
    folded = re.sub(r"\s+", " ", raw.lower())
    lang = detect_language(raw)
    hint = _date_hint(raw, state)
    jail = bool(_JAILBREAK.search(raw))

    if jail:
        return NluResult("unknown", hint, None, None, lang, True, "rules")
    if _contains(folded, _MEDICAL):
        return NluResult("symptom_or_medical", None, None, None, lang, True, "rules")
    if folded == "stop" or _contains(folded, _STOP):
        return NluResult("stop", None, None, None, lang, False, "rules")
    if _contains(folded, _WRONG):
        return NluResult("wrong_number", None, None, None, lang, True, "rules")

    # Digit shortcuts used in the synthetic reminder SMS (1 = confirm, 2 = reschedule).
    if raw.strip() == "1" and state in {"idle", "confirming", "cancelling", "rescheduling"}:
        if state == "cancelling":
            return NluResult("confirm", None, None, True, lang, False, "rules")
        if state == "rescheduling":
            return NluResult("confirm", None, None, True, lang, False, "rules")
        return NluResult("confirm", None, None, True, lang, False, "rules")
    if raw.strip() == "2" and state in {"idle", "confirming"}:
        return NluResult("reschedule", hint, None, None, lang, False, "rules")
    if raw.strip() == "1" and state == "choosing_slot":
        return NluResult("confirm", "slot:1", None, True, lang, False, "rules")
    if raw.strip() == "2" and state == "choosing_slot":
        return NluResult("confirm", "slot:2", None, True, lang, False, "rules")
    if raw.strip() == "3" and state == "choosing_slot":
        return NluResult("confirm", "slot:3", None, True, lang, False, "rules")
    if state == "choosing_slot" and (_contains(folded, _ACCEPT_SLOT) or hint):
        return NluResult("confirm", hint, None, True, lang, False, "rules")

    if state in {"cancelling", "rescheduling"} and folded in {"yes", "ok", "1"}:
        return NluResult("confirm", hint, None, True, lang, False, "rules")
    if state in {"cancelling", "rescheduling"} and folded in {"no", "2"}:
        return NluResult("confirm", None, None, False, lang, False, "rules")

    if _contains(folded, _CANCEL):
        return NluResult("cancel", hint, None, None, lang, False, "rules")
    if _contains(folded, _RESCHEDULE):
        return NluResult("reschedule", hint, None, None, lang, False, "rules")
    if _contains(folded, _ASK):
        return NluResult("ask_slot", hint, None, None, lang, False, "rules")
    if _contains(folded, _CONFIRM) or folded in {"yes", "ok", "1"}:
        return NluResult("confirm", hint, None, True, lang, False, "rules")
    if hint:
        return NluResult("ask_slot", hint, None, None, lang, False, "rules")
    return NluResult("unknown", hint, None, None, lang, False, "rules")


def _parse_llm_json(text: str) -> dict | None:
    blob = text.strip()
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?\s*|\s*```$", "", blob)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", blob, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    intent = data.get("intent")
    if intent not in INTENTS:
        return None
    lang = data.get("language") if data.get("language") in LANGS else "en"
    return {
        "intent": intent,
        "date_hint": data.get("date_hint") or None,
        "time_hint": data.get("time_hint") or None,
        "confirm": data.get("confirm"),
        "language": lang,
        "needs_human": bool(data.get("needs_human")),
    }


_SHORTCUTS = {"1", "2", "3", "stop", "yes", "no", "ok"}
_SAFETY = {"stop", "symptom_or_medical", "wrong_number"}


def understand_llm(text: str, *, state: str = "idle",
                   offered: list | None = None) -> NluResult | None:
    from llm.gateway import complete
    from chatbot.dates import format_sms_date

    payload = {"text": redact_for_model(text), "state": state}
    if offered:
        payload["offered"] = [format_sms_date(d) for d in offered]
    gw = complete(json.dumps(payload, sort_keys=True, default=str),
                  prompt_version="nlu_v1", json_mode=True)
    if not gw.text:
        return None
    data = _parse_llm_json(gw.text)
    if not data:
        return None
    return NluResult(**data, source="llm")


def understand_hybrid(text: str, *, state: str = "idle",
                      offered: list | None = None) -> NluResult:
    """Rules win on safety, 1/2/3, and a spoken pick of an offered day."""
    rules = understand_rules(text, state=state)
    if rules.intent in _SAFETY:
        return rules
    if text.strip().lower() in _SHORTCUTS:
        return rules
    if state == "choosing_slot" and rules.intent == "confirm":
        return rules
    from app.settings import settings

    if (settings.llm_provider or "none").lower() in {"", "none", "off", "template"}:
        return rules
    if not inbound_is_safe_for_model(text):
        return rules
    llm = understand_llm(text, state=state, offered=offered)
    return llm or rules


def understand(text: str, *, state: str = "idle", prefer: str = "auto",
               offered: list | None = None) -> NluResult:
    """prefer: rules | llm | auto (hybrid). Classifier is applied by the service."""
    if prefer == "rules":
        return understand_rules(text, state=state)
    if prefer == "auto":
        return understand_hybrid(text, state=state, offered=offered)
    llm = understand_llm(text, state=state, offered=offered)
    return llm or understand_rules(text, state=state)


def inbound_is_safe_for_model(text: str) -> bool:
    """False if we should skip the LLM and stay on rules (raw phone/name still in the line)."""
    return not any(f.entity in {"PHONE_NUMBER", "PERSON"} for f in scan_text(text))
