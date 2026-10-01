"""Post-check: every number and drug name in the summary must exist in the packet."""

from __future__ import annotations

import re
from dataclasses import dataclass

from llm.deid import Packet

# HEARTS control threshold may appear even when the last reading is different.
PROTOCOL_NUMBERS = {140, 90}
_NUM = re.compile(r"\d+(?:\.\d+)?")
_WORD = re.compile(r"[A-Za-z][A-Za-z-]{2,}")


@dataclass
class CheckResult:
    ok: bool
    extra_numbers: list[str]
    extra_drugs: list[str]
    missing_facts: list[str]


def allowed_numbers(packet: Packet) -> set[str]:
    """Canonical numeric tokens the model may emit."""
    allowed: set[str] = {str(n) for n in PROTOCOL_NUMBERS}
    for part in packet.age_band.replace("+", "-").split("-"):
        if part.isdigit():
            allowed.add(part)
    for bp in [packet.last_bp, *(packet.bp_history or [])]:
        if not bp:
            continue
        allowed.add(str(int(bp["systolic"])))
        allowed.add(str(int(bp["diastolic"])))
    for bs in [packet.last_bs, *(packet.bs_history or [])]:
        if not bs:
            continue
        v = bs["value"]
        allowed.add(str(int(v)) if float(v) == int(v) else str(v))
    for d in packet.drugs:
        for tok in _NUM.findall(d.get("dosage") or ""):
            allowed.add(tok)
            if "." in tok and tok.endswith(".0"):
                allowed.add(tok[:-2])
            if "." in tok and tok.endswith(".5"):
                allowed.add(tok)  # 12.5
    att = packet.attendance
    for key in ("visits_12m", "missed_12m", "days_overdue"):
        if att.get(key) is not None:
            allowed.add(str(int(att[key])))
    blob = packet.canonical_json()
    for tok in _NUM.findall(blob):
        allowed.add(tok)
        if tok.endswith(".0"):
            allowed.add(tok[:-2])
    return allowed


def allowed_drugs(packet: Packet) -> set[str]:
    return {d["name"].lower() for d in packet.drugs if d.get("name")}


def extract_numbers(text: str) -> list[str]:
    return _NUM.findall(text)


def extra_numbers(text: str, packet: Packet) -> list[str]:
    allow = allowed_numbers(packet)
    extra: list[str] = []
    for tok in extract_numbers(text):
        if tok in allow:
            continue
        if tok.endswith(".0") and tok[:-2] in allow:
            continue
        extra.append(tok)
    return extra


def extra_drugs(text: str, packet: Packet) -> list[str]:
    """Flag drug-like tokens that are not on the patient's list.

    Only known HEARTS / common NCD names are considered, so ordinary English
    is not treated as a medication.
    """
    known = {
        "amlodipine",
        "telmisartan",
        "chlorthalidone",
        "metformin",
        "losartan",
        "lisinopril",
        "atenolol",
        "hydrochlorothiazide",
        "nifedipine",
        "enalapril",
        "glibenclamide",
        "insulin",
        "aspirin",
        "atorvastatin",
        "simvastatin",
    }
    allow = allowed_drugs(packet)
    # Next-step guidance is written by code into the packet; those names are not inventions.
    blob = packet.canonical_json().lower()
    allow |= {w for w in known if w in blob}
    found = {w.lower() for w in _WORD.findall(text)}
    return sorted((found & known) - allow)


def must_keep_facts(packet: Packet) -> list[str]:
    """Facts a good summary should keep. Used by the post-check omission list and eval."""
    facts: list[str] = []
    if packet.last_bp:
        facts.append(f"{packet.last_bp['systolic']}/{packet.last_bp['diastolic']}")
    for d in packet.drugs:
        facts.append(d["name"])
    if packet.risk and packet.risk.get("band"):
        facts.append(packet.risk["band"])
    if packet.attendance.get("missed_12m"):
        facts.append("missed")
    if packet.last_call:
        facts.append(packet.last_call["result"].replace("_", " "))
    return facts


def missing_facts(text: str, packet: Packet) -> list[str]:
    low = text.lower()
    missing: list[str] = []
    for fact in must_keep_facts(packet):
        if fact.lower() not in low:
            missing.append(fact)
    return missing


def check_summary(text: str, packet: Packet) -> CheckResult:
    extras_n = extra_numbers(text, packet)
    extras_d = extra_drugs(text, packet)
    # Invented numbers or drugs fail the check. Omission is reported but does
    # not fail: a short model reply still beats a hallucinated chart.
    ok = not extras_n and not extras_d
    return CheckResult(ok=ok, extra_numbers=extras_n, extra_drugs=extras_d, missing_facts=missing_facts(text, packet))
