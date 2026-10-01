"""Build an identity-free clinical packet (ADR-0003).

The packet is the only object a model is allowed to see. Names, phones,
addresses, national IDs, exact calendar dates and free-text notes are refused.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from llm.scan import scan_obj, scan_text

FORBIDDEN_KEYS = {
    "full_name",
    "name",
    "first_name",
    "last_name",
    "phone",
    "phone_number",
    "number",
    "street_address",
    "village_or_colony",
    "village",
    "address",
    "date_of_birth",
    "dob",
    "nin",
    "national_id",
    "notes",
    "note",
    "free_text",
    "body",
    "email",
    "patient_name",
}

AGE_BANDS = [
    (17, "0-17"),
    (24, "18-24"),
    (34, "25-34"),
    (44, "35-44"),
    (54, "45-54"),
    (64, "55-64"),
    (74, "65-74"),
]


class DeidError(ValueError):
    """Packet construction refused because identity or free text was present."""


def new_case_code() -> str:
    """Random per-request code. Not derived from any patient attribute."""
    return "C-" + secrets.token_hex(3).upper()


def age_band(age: int | None) -> str:
    if age is None:
        return "unknown"
    for hi, label in AGE_BANDS:
        if age <= hi:
            return label
    return "75+"


def _as_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def relative_when(ts, as_of: date) -> str:
    """Human relative time. Never returns a calendar date."""
    d = _as_date(ts)
    delta = (as_of - d).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta == -1:
        return "tomorrow"
    if delta < 0:
        n = -delta
        if n < 7:
            return f"in {n} days"
        if n < 60:
            w = max(n // 7, 1)
            return f"in {w} week" if w == 1 else f"in {w} weeks"
        m = max(n // 30, 1)
        return f"in {m} month" if m == 1 else f"in {m} months"
    if delta < 7:
        return f"{delta} days ago"
    if delta < 60:
        w = max(delta // 7, 1)
        return "1 week ago" if w == 1 else f"{w} weeks ago"
    if delta < 730:
        m = max(delta // 30, 1)
        return "1 month ago" if m == 1 else f"{m} months ago"
    y = max(delta // 365, 1)
    return "1 year ago" if y == 1 else f"{y} years ago"


def _refuse_if_forbidden(record: dict) -> None:
    hit = set(record) & FORBIDDEN_KEYS
    if hit:
        raise DeidError(f"refused: identity or free-text field present ({sorted(hit)})")


def _refuse_if_pii(obj, where: str) -> None:
    findings = scan_obj(obj)
    if findings:
        kinds = sorted({f.entity for f in findings})
        raise DeidError(f"refused: {where} contains {kinds}")


@dataclass
class Packet:
    case_code: str
    age_band: str
    sex: str
    conditions: list[str]
    bp_history: list[dict]
    last_bp: dict | None
    bs_history: list[dict]
    last_bs: dict | None
    drugs: list[dict]
    attendance: dict
    last_call: dict | None
    risk: dict | None
    program_status: str
    suggested_next_step: str
    extra: dict = field(default_factory=dict)

    def to_prompt(self) -> dict:
        """Payload the model may see. Case code stays on our side of the boundary."""
        d = asdict(self)
        d.pop("case_code", None)
        d.pop("extra", None)
        return d

    def to_facts(self) -> dict:
        return self.to_prompt()

    def canonical_json(self) -> str:
        return json.dumps(self.to_prompt(), sort_keys=True, default=str)

    def packet_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def _bp_row(sys: int, dia: int, when: str) -> dict:
    return {
        "systolic": int(sys),
        "diastolic": int(dia),
        "when": when,
        "controlled": int(sys) < 140 and int(dia) < 90,
    }


def _suggested_next_step(last_bp: dict | None, program_status: str, last_call: dict | None,
                         drugs: list | None = None) -> str:
    from reckoner.next_step import next_step as hearts_next

    if last_bp:
        ns = hearts_next(last_bp["systolic"], last_bp["diastolic"], drugs or [])
        if program_status == "overdue" and ns.action == "continue":
            return ns.guidance + " Call to bring the overdue visit back."
        if program_status == "pre_visit" and ns.action == "continue":
            return ns.guidance + " Reminder call before the upcoming visit."
        return ns.guidance
    if program_status == "overdue":
        if last_call and last_call.get("result") == "remind_to_call_later":
            return "Return call is due — confirm the visit date."
        return "Call to bring the overdue visit back."
    if program_status == "pre_visit":
        return "Reminder call before the upcoming visit."
    return "Continue the current plan; no drug change from this summary."


def build_packet(record: dict, *, as_of: date | None = None, case_code: str | None = None) -> Packet:
    """Build a packet from structured fields only. Raises DeidError on any PII."""
    _refuse_if_forbidden(record)
    _refuse_if_pii(record, "input")

    as_of = as_of or date.today()
    sex = str(record.get("sex") or record.get("gender") or "unknown")
    conditions: list[str] = []
    if str(record.get("hypertension", "yes")).lower() in {"yes", "true", "1"}:
        conditions.append("hypertension")
    if str(record.get("diabetes", "no")).lower() in {"yes", "true", "1"}:
        conditions.append("diabetes")

    bp_history: list[dict] = []
    for row in record.get("bp_history") or []:
        bp_history.append(_bp_row(row["systolic"], row["diastolic"], relative_when(row["recorded_at"], as_of)))
    last_bp = bp_history[0] if bp_history else None

    bs_history: list[dict] = []
    for row in record.get("bs_history") or []:
        bs_history.append(
            {
                "type": row.get("blood_sugar_type") or row.get("type") or "random",
                "value": float(row["blood_sugar_value"] if "blood_sugar_value" in row else row["value"]),
                "when": relative_when(row["recorded_at"], as_of),
            }
        )
    last_bs = bs_history[0] if bs_history else None

    drugs = []
    for row in record.get("drugs") or []:
        drugs.append(
            {
                "name": str(row["name"]),
                "dosage": str(row.get("dosage") or ""),
                "frequency": str(row.get("frequency") or "OD"),
            }
        )

    att_in = record.get("attendance") or {}
    visits = int(att_in.get("visits_12m") or 0)
    missed = int(att_in.get("missed_12m") or 0)
    last_visit = att_in.get("last_visit_at")
    next_sched = att_in.get("next_scheduled_at")
    days_overdue = att_in.get("days_overdue")
    attendance = {
        "visits_12m": visits,
        "missed_12m": missed,
        "last_visit": relative_when(last_visit, as_of) if last_visit else "never",
        "next_scheduled": relative_when(next_sched, as_of) if next_sched else None,
        "days_overdue": int(days_overdue) if days_overdue is not None else None,
    }

    last_call = None
    if record.get("last_call"):
        lc = record["last_call"]
        last_call = {
            "result": lc["result_type"] if "result_type" in lc else lc["result"],
            "when": relative_when(lc["recorded_at"] if "recorded_at" in lc else lc["when"], as_of)
            if (lc.get("recorded_at") or lc.get("when"))
            else "unknown",
        }
        if lc.get("remove_reason"):
            last_call["remove_reason"] = str(lc["remove_reason"])

    risk = None
    if record.get("risk"):
        rk = record["risk"]
        risk = {
            "band": rk.get("band"),
            "basis": rk.get("basis"),
            "reasons": list(rk.get("reasons") or [])[:4],
        }

    status = str(record.get("program_status") or "under_care")
    packet = Packet(
        case_code=case_code or new_case_code(),
        age_band=age_band(record.get("age")),
        sex=sex,
        conditions=conditions,
        bp_history=bp_history[:6],
        last_bp=last_bp,
        bs_history=bs_history[:4],
        last_bs=last_bs,
        drugs=drugs,
        attendance=attendance,
        last_call=last_call,
        risk=risk,
        program_status=status,
        suggested_next_step=_suggested_next_step(last_bp, status, last_call, drugs),
    )
    payload = packet.to_prompt()
    _refuse_if_pii(payload, "packet")
    # Belt: no ISO date should survive relative_when.
    blob = packet.canonical_json()
    if scan_text(blob):
        raise DeidError("refused: packet serialisation still contains PII")
    return packet
