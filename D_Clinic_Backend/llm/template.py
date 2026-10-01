"""Deterministic five-line briefing. Used when no model is configured or a check fails."""

from __future__ import annotations

from llm.deid import Packet


def templated_summary(packet: Packet) -> str:
    sex = packet.sex
    cond = " and ".join(packet.conditions) if packet.conditions else "hypertension program"
    if packet.last_bp:
        bp = packet.last_bp
        target = "at the 140/90 program target" if bp["controlled"] else "above the 140/90 program target"
        line1 = (
            f"{packet.age_band} {sex} patient on the {cond} register. "
            f"Last BP {bp['systolic']}/{bp['diastolic']} ({bp['when']}), {target}."
        )
    else:
        line1 = f"{packet.age_band} {sex} patient on the {cond} register. No blood pressure recorded yet."

    if packet.drugs:
        meds = ", ".join(f"{d['name']} {d['dosage']}".strip() for d in packet.drugs)
        line2 = f"Current drugs: {meds}."
    else:
        line2 = "No protocol drug recorded."

    att = packet.attendance
    missed = att.get("missed_12m") or 0
    visits = att.get("visits_12m") or 0
    last = att.get("last_visit") or "never"
    if att.get("days_overdue") is not None and packet.program_status == "overdue":
        line3 = (
            f"Attendance: {visits} visits in 12 months, {missed} missed; "
            f"last visit {last}; overdue by {att['days_overdue']} days."
        )
    elif att.get("next_scheduled"):
        line3 = (
            f"Attendance: {visits} visits in 12 months, {missed} missed; "
            f"last visit {last}; next visit {att['next_scheduled']}."
        )
    else:
        line3 = f"Attendance: {visits} visits in 12 months, {missed} missed; last visit {last}."

    if packet.last_call:
        result = packet.last_call["result"].replace("_", " ")
        line4 = f"Last call ({packet.last_call['when']}): {result}."
    else:
        line4 = "No call result on record."

    if packet.risk and packet.risk.get("band"):
        reasons = "; ".join(packet.risk.get("reasons") or [])
        extra = f" ({reasons})" if reasons else ""
        line5 = (
            f"Missed-visit risk band {packet.risk['band']}, basis {packet.risk.get('basis') or 'unknown'}{extra}. "
            f"{packet.suggested_next_step}"
        )
    else:
        line5 = packet.suggested_next_step

    return " ".join([line1, line2, line3, line4, line5])
