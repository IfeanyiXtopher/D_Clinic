"""Evaluate worker summaries on 200 de-identified packets.

Runs three generators:
  * template — deterministic briefing (always available)
  * sloppy   — invents a BP, a drug and a name (shows why the post-check exists)
  * pipeline — sloppy text through summarize_packet (must fall back)
  * live     — optional, if LLM_PROVIDER is ollama or openai and reachable

Writes ``docs/eval_reports/summary.md`` and ``data/eval_sets/must_keep_facts.json``.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from app.settings import REPO_ROOT
from llm.check import check_summary, must_keep_facts
from llm.deid import Packet, build_packet
from llm.scan import scan_text
from llm.summary import summarize_packet
from llm.template import templated_summary

AS_OF = date(2026, 9, 26)
N_PACKETS = 200
REPORT_PATH = REPO_ROOT / "docs" / "eval_reports" / "summary.md"
FACTS_PATH = REPO_ROOT / "data" / "eval_sets" / "must_keep_facts.json"

DRUGS = [
    [("Amlodipine", "5 mg")],
    [("Amlodipine", "10 mg")],
    [("Amlodipine", "10 mg"), ("Telmisartan", "40 mg")],
    [("Amlodipine", "10 mg"), ("Telmisartan", "80 mg")],
    [("Amlodipine", "10 mg"), ("Telmisartan", "80 mg"), ("Chlorthalidone", "12.5 mg")],
    [("Metformin", "500 mg")],
]
BPS = [(156, 94), (128, 78), (168, 102), (142, 88), (118, 76), (150, 96), (134, 86), (176, 110)]
CALLS = [None, "agreed_to_visit", "remind_to_call_later", "removed_from_overdue_list"]
BANDS = ["low", "medium", "high"]
SEXES = ["female", "male", "transgender"]

OVERREACH = re.compile(
    r"\b(diagnos|prescrib|start insulin|titrate|increase the dose|you have|stroke|infarct)\b",
    re.I,
)


def _record(i: int) -> dict:
    rng = i * 17 + 11
    age = 28 + (rng % 55)
    sys, dia = BPS[i % len(BPS)]
    days_ago = 5 + (i * 3) % 80
    drugs = [{"name": n, "dosage": d, "frequency": "OD"} for n, d in DRUGS[i % len(DRUGS)]]
    call = CALLS[i % len(CALLS)]
    status = ["overdue", "pre_visit", "under_care", "overdue"][i % 4]
    missed = i % 5
    visits = 2 + (i % 6)
    rec = {
        "age": age,
        "gender": SEXES[i % 3],
        "hypertension": "yes",
        "diabetes": "yes" if i % 7 == 0 else "no",
        "bp_history": [{"systolic": sys, "diastolic": dia, "recorded_at": AS_OF - timedelta(days=days_ago)}],
        "bs_history": (
            [{"blood_sugar_type": "random", "blood_sugar_value": 8.4 + (i % 5), "recorded_at": AS_OF - timedelta(days=days_ago)}]
            if i % 7 == 0
            else []
        ),
        "drugs": drugs,
        "attendance": {
            "visits_12m": visits,
            "missed_12m": missed,
            "last_visit_at": AS_OF - timedelta(days=days_ago),
            "next_scheduled_at": AS_OF + timedelta(days=4) if status == "pre_visit" else None,
            "days_overdue": 12 + (i % 40) if status == "overdue" else None,
        },
        "last_call": (
            {"result_type": call, "recorded_at": AS_OF - timedelta(days=3 + i % 10)} if call else None
        ),
        "risk": {"band": BANDS[i % 3], "basis": ["personal", "mixed", "group"][i % 3],
                 "reasons": ["uncontrolled BP"] if sys >= 140 else ["recent missed visit"]},
        "program_status": status,
    }
    if i % 23 == 0:
        rec["bp_history"] = []
        rec["attendance"]["last_visit_at"] = None
    if i % 29 == 0:
        rec["drugs"] = []
    return rec


def build_eval_set(n: int = N_PACKETS) -> list[Packet]:
    packets = []
    for i in range(n):
        packets.append(build_packet(_record(i), as_of=AS_OF, case_code=f"C-EVAL{i:03d}"))
    return packets


def sloppy_text(packet: Packet) -> str:
    """A bad model: invents a reading, a drug, a name and a phone."""
    base = templated_summary(packet)
    return base + " Last BP was 200/130 on Losartan. Call Mr Adebayo at 08031234567."


def pdsqi(text: str, packet: Packet) -> dict[str, int]:
    chk = check_summary(text, packet)
    facts = must_keep_facts(packet)
    kept = sum(1 for f in facts if f.lower() in text.lower())
    words = len(text.split())
    lines = max(text.count(".") + text.count("!") + text.count("?"), 1)
    actionable = any(w in text.lower() for w in ("call", "visit", "overdue", "risk", "adherence", "remind", "confirm"))
    return {
        "accuracy": int(chk.ok),
        "completeness": int(bool(facts) and kept / len(facts) >= 0.6),
        "medication_fidelity": int(not chk.extra_drugs and all(d["name"].lower() in text.lower() for d in packet.drugs)),
        "bp_fidelity": int(
            not packet.last_bp
            or f"{packet.last_bp['systolic']}/{packet.last_bp['diastolic']}" in text
        ),
        "no_identity": int(not scan_text(text)),
        "relative_time": int(not re.search(r"\d{4}-\d{2}-\d{2}", text)),
        "length": int(3 <= lines <= 8 and 25 <= words <= 180),
        "actionability": int(actionable),
        "no_overreach": int(not OVERREACH.search(text)),
    }


def score_texts(name: str, pairs: list[tuple[Packet, str]]) -> dict:
    rows = []
    for packet, text in pairs:
        chk = check_summary(text, packet)
        rubric = pdsqi(text, packet)
        facts = must_keep_facts(packet)
        kept = sum(1 for f in facts if f.lower() in text.lower())
        rows.append({
            "ok": chk.ok,
            "omission": 1 - (kept / len(facts) if facts else 1),
            "words": len(text.split()),
            "pii": int(bool(scan_text(text))),
            "pdsqi": rubric,
            "pdsqi_mean": sum(rubric.values()) / 9,
        })
    n = len(rows)
    return {
        "name": name,
        "n": n,
        "factuality": sum(r["ok"] for r in rows) / n,
        "omission": sum(r["omission"] for r in rows) / n,
        "mean_words": sum(r["words"] for r in rows) / n,
        "pii_rate": sum(r["pii"] for r in rows) / n,
        "pdsqi": {k: sum(r["pdsqi"][k] for r in rows) / n for k in rows[0]["pdsqi"]},
        "pdsqi_mean": sum(r["pdsqi_mean"] for r in rows) / n,
    }


def _try_live(packets: list[Packet]) -> dict | None:
    from app.settings import settings
    from llm.gateway import complete

    if (settings.llm_provider or "none").lower() in {"", "none", "off", "template"}:
        return None
    sample = packets[:40]
    pairs = []
    used = 0
    for p in sample:
        gw = complete(json.dumps(p.to_prompt(), sort_keys=True))
        if not gw.text:
            continue
        used += 1
        pairs.append((p, gw.text))
    if not pairs:
        return {"name": f"live:{settings.llm_provider}", "n": 0, "error": "provider configured but returned no text"}
    s = score_texts(f"live:{settings.llm_provider}/{settings.openai_model if settings.llm_provider=='openai' else settings.ollama_model}", pairs)
    s["n_attempted"] = len(sample)
    s["n_got_text"] = used
    return s


def write_facts(packets: list[Packet]) -> None:
    FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"case_code": p.case_code, "must_keep": must_keep_facts(p), "packet": p.to_prompt()} for p in packets]
    FACTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render(scores: list[dict], fallback_rate: float, live: dict | None) -> str:
    def row(s: dict) -> str:
        if s.get("error"):
            return f"| {s['name']} | {s.get('n', 0)} | — | — | — | — | {s['error']} |"
        return (
            f"| {s['name']} | {s['n']} | {s['factuality']:.2f} | {s['omission']:.2f} | "
            f"{s['mean_words']:.0f} | {s['pii_rate']:.2f} | {s['pdsqi_mean']:.2f} |"
        )

    pdsqi_keys = [
        "accuracy", "completeness", "medication_fidelity", "bp_fidelity",
        "no_identity", "relative_time", "length", "actionability", "no_overreach",
    ]
    tmpl = next(s for s in scores if s["name"] == "template")

    lines = [
        "# Patient summary evaluation",
        "",
        "Auto-generated by `python -m llm.eval_summary`. "
        f"{N_PACKETS} de-identified packets, as-of {AS_OF.isoformat()}. "
        "Identity is never in a packet. A summary fails factuality if it invents a number or a drug.",
        "",
        "## Headline",
        "",
        f"The templated briefing keeps **{tmpl['factuality']:.0%}** factuality, "
        f"**{1 - tmpl['omission']:.0%}** of must-keep facts, PDSQI-9-style mean "
        f"**{tmpl['pdsqi_mean']:.2f}**, and **{tmpl['pii_rate']:.0%}** PII. "
        f"A sloppy model that invents BP 200/130, Losartan and a name is caught; "
        f"the pipeline falls back on **{fallback_rate:.0%}** of those packets and recovers template quality.",
        "",
        "Live Ollama / OpenAI is optional. If `LLM_PROVIDER` is unset the live row is skipped — "
        "the 1 GB VPS path is template + OpenAI later, same checks.",
        "",
        "## Generators",
        "",
        "| generator | n | factuality (no extra number/drug) | omission (must-keep missing) | mean words | PII rate | PDSQI-9 mean |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in scores:
        lines.append(row(s))
    if live:
        lines.append(row(live))
    lines += [
        "",
        "## PDSQI-9-style rubric (template)",
        "",
        "Adapted from clinical-summary quality inventories for a health-worker briefing. Each item is 0/1.",
        "",
        "| item | pass rate |",
        "|---|---:|",
    ]
    for k in pdsqi_keys:
        lines.append(f"| {k.replace('_', ' ')} | {tmpl['pdsqi'][k]:.2f} |")
    lines += [
        "",
        "## What this shows",
        "",
        "* The template is the safety floor: every number and drug comes from the packet.",
        "* A model that hallucinates is not shown to the worker — `failed_fallback` swaps in the template.",
        "* Switching `LLM_PROVIDER` from `ollama` to `openai` does not change the de-id boundary or the check.",
        "",
        "## Caveats",
        "",
        "Packets are constructed from the same HEARTS ladder and Simple vocabulary as the synthetic cohort, "
        "not sampled from the live database, so the eval runs without Postgres or a GPU. "
        "A live-provider row, when present, is a convenience check — promotion still needs the same "
        "factuality threshold on real (de-identified) program packets.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    packets = build_eval_set()
    write_facts(packets)
    template_pairs = [(p, templated_summary(p)) for p in packets]
    sloppy_pairs = [(p, sloppy_text(p)) for p in packets]
    pipe_pairs = []
    fallbacks = 0
    for p in packets:
        res = summarize_packet(p, complete_fn=lambda _payload, _p=p: _gw(sloppy_text(_p)))
        pipe_pairs.append((p, res.summary))
        if res.fallback_used:
            fallbacks += 1
    scores = [
        score_texts("template", template_pairs),
        score_texts("sloppy (unchecked)", sloppy_pairs),
        score_texts("sloppy + pipeline", pipe_pairs),
    ]
    live = _try_live(packets)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render(scores, fallbacks / len(packets), live), encoding="utf-8")
    print(f"wrote {REPORT_PATH} ({len(packets)} packets, fallback {fallbacks}/{len(packets)})")
    print(f"wrote {FACTS_PATH}")
    for s in scores:
        print(f"  {s['name']}: factuality={s['factuality']:.2f} omission={s['omission']:.2f} pdsqi={s['pdsqi_mean']:.2f} pii={s['pii_rate']:.2f}")


def _gw(text: str):
    from llm.gateway import GatewayResult, PROMPT_VERSION

    return GatewayResult(text, "mock", "sloppy", PROMPT_VERSION, 1, 10, 20, None)


if __name__ == "__main__":
    main()
