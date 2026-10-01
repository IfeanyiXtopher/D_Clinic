"""Deterministic HEARTS next-step table: BP band × current protocol drugs.

Used by the ready-reckoner API and by Step 4 ``suggested_next_step``.
Output is guidance for a clinician, never a prescription.
"""

from __future__ import annotations

from dataclasses import dataclass

# Matches data/synth/generate.py HTN_LADDER.
STEPS: list[tuple[int, frozenset[tuple[str, str]], str]] = [
    (1, frozenset({("amlodipine", "5")}), "amlodipine 5 mg once daily"),
    (2, frozenset({("amlodipine", "10")}), "amlodipine 10 mg once daily"),
    (3, frozenset({("amlodipine", "10"), ("telmisartan", "40")}),
     "amlodipine 10 mg plus telmisartan 40 mg once daily"),
    (4, frozenset({("amlodipine", "10"), ("telmisartan", "80")}),
     "amlodipine 10 mg plus telmisartan 80 mg once daily"),
    (5, frozenset({("amlodipine", "10"), ("telmisartan", "80"), ("chlorthalidone", "12.5")}),
     "amlodipine 10 mg plus telmisartan 80 mg plus chlorthalidone 12.5 mg once daily"),
]

NEXT_CITE = {1: "H-05", 2: "H-06", 3: "H-07", 4: "H-08", 5: "H-18"}


@dataclass(frozen=True)
class NextStep:
    controlled: bool
    current_step: int | None
    action: str  # continue | step_up | start_step_1 | refer | confirm_reading
    guidance: str
    cite: str
    next_regimen: str | None


def _norm_drugs(drugs: list[dict]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for d in drugs or []:
        name = str(d.get("name") or "").strip().lower()
        dosage = str(d.get("dosage") or "")
        num = "".join(ch if ch.isdigit() or ch == "." else " " for ch in dosage).split()
        strength = num[0] if num else ""
        if name:
            out.add((name, strength))
    return out


def current_ladder_step(drugs: list[dict]) -> int | None:
    have = _norm_drugs(drugs)
    if not have:
        return None
    # Highest matching step (subset match on name+mg).
    matched = None
    for step, req, _ in STEPS:
        if req <= have:
            matched = step
    return matched


def next_step(systolic: int | None, diastolic: int | None, drugs: list[dict] | None = None) -> NextStep:
    drugs = drugs or []
    step = current_ladder_step(drugs)
    if systolic is None or diastolic is None:
        return NextStep(False, step, "confirm_reading",
                        "No clinic blood pressure on record. Measure before any protocol step.",
                        "H-02", None)
    controlled = int(systolic) < 140 and int(diastolic) < 90
    if int(systolic) >= 180 or int(diastolic) >= 120:
        return NextStep(False, step, "refer",
                        "Clinic BP is in the urgent range. Recheck and refer the same day. "
                        "Do not titrate from this table.",
                        "H-10", None)
    if controlled:
        return NextStep(True, step, "continue",
                        "BP is at the 140/90 program target. Continue the current plan; "
                        "do not change drugs from this table.",
                        "H-09", None)
    if step is None:
        return NextStep(False, None, "start_step_1",
                        "Confirmed BP is above 140/90 and no protocol drug is on record. "
                        "Protocol start is amlodipine 5 mg once daily — clinician to prescribe.",
                        "H-04", "amlodipine 5 mg once daily")
    if step >= 5:
        return NextStep(False, 5, "refer",
                        "BP remains above 140/90 on three protocol drugs. Refer. "
                        "Do not add a fourth agent from this table.",
                        "H-18", None)
    nxt = STEPS[step]  # next index is current step (1-based)
    _, _, regimen = nxt
    return NextStep(
        False, step, "step_up",
        f"Confirmed BP is above 140/90 on step {step}. Protocol next step is {regimen}. "
        "Clinician reviews adherence and signs the change. Not a prescription from this tool.",
        NEXT_CITE[step],
        regimen,
    )
