"""Evaluate ready-reckoner retrieval and grounded answers.

Writes ``docs/eval_reports/reckoner.md`` and ``data/eval_sets/reckoner_qa.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.settings import REPO_ROOT
from reckoner.ask import REFUSAL, ask, dose_check
from reckoner.index import build_index
from reckoner.next_step import next_step
from reckoner.retrieve import retrieve

REPORT = REPO_ROOT / "docs" / "eval_reports" / "reckoner.md"
QA_PATH = REPO_ROOT / "data" / "eval_sets" / "reckoner_qa.json"


def gold_set() -> list[dict]:
    in_scope = [
        ("What is the clinic blood pressure target?", "H-01"),
        ("When is BP considered controlled?", "H-01"),
        ("Is 139/89 at goal?", "H-01"),
        ("How should staff measure blood pressure?", "H-02"),
        ("Should we change drugs from one home BP on SMS?", "H-02"),
        ("What lifestyle advice is given at every visit?", "H-03"),
        ("Does walking replace a drug step-up?", "H-03"),
        ("What is the first protocol drug if not yet on treatment?", "H-04"),
        ("What dose of amlodipine is step 1?", "H-04"),
        ("Patient on amlodipine 5 mg still 148/92. Next step?", "H-05"),
        ("When do we increase amlodipine from 5 to 10 mg?", "H-05"),
        ("Ankle swelling after raising amlodipine — stop the drug from this tool?", "H-13"),
        ("On amlodipine 10 mg, BP still high. What is added?", "H-06"),
        ("What is HEARTS step 3?", "H-06"),
        ("Can this tool start telmisartan in pregnancy?", "H-06"),
        ("On amlodipine 10 and telmisartan 40, still uncontrolled. Next?", "H-07"),
        ("What is the telmisartan dose at step 4?", "H-07"),
        ("When is chlorthalidone 12.5 mg added?", "H-08"),
        ("What is HEARTS step 5?", "H-08"),
        ("Uncontrolled on three protocol drugs. What now?", "H-08"),
        ("BP 128/78 on current drugs. Step up?", "H-09"),
        ("If BP is below 140/90 do we change the regimen?", "H-09"),
        ("Systolic 190. What should the worker do?", "H-10"),
        ("Diastolic 122 with headache. Remote titration?", "H-10"),
        ("How soon to review after a step-up?", "H-11"),
        ("What is the follow-up interval when controlled?", "H-11"),
        ("Patient missed yesterday's tablet. Double today's dose?", "H-12"),
        ("What to do after a missed dose?", "H-12"),
        ("Amlodipine and swollen ankles. Emergency?", "H-13"),
        ("Face swelling and trouble breathing on amlodipine.", "H-13"),
        ("Does diabetes change the 140/90 target in this program?", "H-14"),
        ("Is metformin a HEARTS hypertension step?", "H-14"),
        ("Poor adherence and high BP. Add a third drug from this tool?", "H-15"),
        ("What to check before a step-up?", "H-15"),
        ("Which topics must the ready-reckoner refuse?", "H-16"),
        ("Is this tool only for adult hypertension follow-up?", "H-16"),
        ("Pregnant woman with high BP. Use the ladder?", "H-17"),
        ("Is telmisartan allowed in pregnancy?", "H-17"),
        ("When do we refer for hypertension?", "H-18"),
        ("Age under 18 with high BP.", "H-18"),
        ("May the worker tell the patient a new dose as already prescribed?", "H-19"),
        ("What may the worker explain about 140/90?", "H-19"),
        ("High blood sugar — change the hypertension ladder?", "H-20"),
        ("Should we start insulin from this protocol?", "H-20"),
        ("Who is the national PHC protocol for?", "N-01"),
        ("Are children treated on this PHC protocol?", "N-01"),
        ("Can one SMS home reading start a step-up?", "N-02"),
        ("How is hypertension confirmed at PHC?", "N-02"),
        ("What is first-line at PHC in this adaptation?", "N-03"),
        ("Can the tool substitute lisinopril as first-line?", "N-03"),
        ("When is the two-drug combination used at PHC?", "N-04"),
        ("Telmisartan 40 mg with amlodipine 10 — which step?", "N-04"),
        ("What diuretic is the third protocol agent?", "N-05"),
        ("Chlorthalidone out of stock — will the tool name a substitute?", "N-05"),
        ("May a CHEW create a new prescription from the reckoner?", "N-06"),
        ("Who signs a step-up?", "N-06"),
        ("How many days of supply at a controlled visit?", "N-07"),
        ("Should the model order an extra bottle for an overdue patient?", "N-07"),
        ("Dizziness after a step-up at PHC.", "N-08"),
        ("Hot weather and chlorthalidone — what to watch?", "N-08"),
        ("Diabetes plus hypertension at the same PHC. Target?", "N-09"),
        ("Start insulin from the national HTN protocol?", "N-09"),
        ("Where can a chunk id be written?", "N-10"),
        ("May a patient name go in the question box?", "N-10"),
        ("What does 140/90 mean for the program?", "H-01"),
        ("Repeat the BP if the first reading is high?", "H-02"),
        ("Salt advice for hypertension.", "H-03"),
        ("Start amlodipine 5 mg — is that step 1?", "H-04"),
        ("Amlodipine 5 mg not at goal after confirmation.", "H-05"),
        ("Add telmisartan after amlodipine 10 mg.", "H-06"),
        ("Increase telmisartan from 40 to 80 mg.", "H-07"),
        ("Add chlorthalidone after telmisartan 80 mg.", "H-08"),
        ("Continue current drugs when controlled.", "H-09"),
        ("BP 180 systolic — same-day referral?", "H-10"),
        ("Review in four weeks after a new drug.", "H-11"),
        ("Do not take two doses at once.", "H-12"),
        ("Refer if still high on three drugs.", "H-18"),
        ("Pregnancy is not treated with this ladder.", "H-17"),
        ("28-day refill at PHC.", "N-07"),
        ("First-line is amlodipine not losartan.", "N-03"),
    ]
    oos = [
        "What artemether dose for severe malaria?",
        "How do I set the INR for warfarin this week?",
        "Childhood asthma: salbutamol nebule schedule?",
        "Which chemotherapy cycle follows FOLFOX?",
        "How to reduce a Colles fracture in plaster?",
        "COVID vaccine booster interval for a 12-year-old?",
        "SSRI choice for first-episode depression?",
        "Measles isolation days in the ward?",
        "Cataract surgery intraocular lens power?",
        "Appendicitis — start antibiotics at home?",
        "What plaster of Paris layers for a tibia fracture?",
        "Malaria RDT negative, still give ACT?",
        "Warfarin tablet colour for INR 4.5?",
        "Salbutamol inhaler for a toddler wheeze now?",
        "Cancer pain: start morphine from this protocol?",
        "How many measles vaccines after exposure?",
        "Depression: can I stop the SSRI from this chat?",
        "COVID vaccine and amlodipine interaction?",
        "Fracture clinic next-step after X-ray?",
        "Chemotherapy antiemetic protocol day 1?",
    ]
    rows = [{"id": f"g{i:03d}", "question": q, "must_chunk": cid, "oos": False}
            for i, (q, cid) in enumerate(in_scope, start=1)]
    rows += [{"id": f"o{i:03d}", "question": q, "must_chunk": None, "oos": True}
             for i, q in enumerate(oos, start=1)]
    return rows


def evaluate(rows: list[dict], index) -> dict:
    recall_hits = 0
    recall_n = 0
    faithful = 0
    answered = 0
    refuse_ok = 0
    oos_n = 0
    in_refuse = 0
    in_n = 0
    details = []
    for row in rows:
        res = ask(row["question"], index=index)
        if row["oos"]:
            oos_n += 1
            refuse_ok += int(res.refused)
        else:
            in_n += 1
            in_refuse += int(res.refused)
            hits = retrieve(row["question"], index=index)
            recall_n += 1
            if row["must_chunk"] in {h.chunk.id for h in hits}:
                recall_hits += 1
            if not res.refused:
                answered += 1
                if dose_check(res.answer, hits):
                    faithful += 1
        details.append({**row, "refused": res.refused, "answer": res.answer[:180],
                        "cites": [c["id"] for c in res.citations]})
    return {
        "n": len(rows),
        "in_n": in_n,
        "oos_n": oos_n,
        "recall_at_4": recall_hits / recall_n if recall_n else 0,
        "faithfulness": faithful / answered if answered else 0,
        "answered": answered,
        "refusal_accuracy": refuse_ok / oos_n if oos_n else 0,
        "in_scope_refusal": in_refuse / in_n if in_n else 0,
        "details": details,
    }


def next_step_selfcheck() -> dict:
    cases = [
        (128, 78, [{"name": "Amlodipine", "dosage": "5 mg"}], "continue"),
        (156, 94, [{"name": "Amlodipine", "dosage": "5 mg"}], "step_up"),
        (156, 94, [], "start_step_1"),
        (190, 100, [{"name": "Amlodipine", "dosage": "10 mg"}], "refer"),
        (150, 96, [{"name": "Amlodipine", "dosage": "10 mg"},
                    {"name": "Telmisartan", "dosage": "80 mg"},
                    {"name": "Chlorthalidone", "dosage": "12.5 mg"}], "refer"),
    ]
    ok = 0
    for sys, dia, drugs, action in cases:
        if next_step(sys, dia, drugs).action == action:
            ok += 1
    return {"n": len(cases), "ok": ok}


def render(m: dict, table: dict) -> str:
    return "\n".join([
        "# Ready-reckoner evaluation",
        "",
        "Auto-generated by `python -m reckoner.eval_reckoner`. "
        f"{m['in_n']} in-scope gold questions and {m['oos_n']} out-of-scope questions. "
        "Retrieval is TF-IDF over protocol chunks (local embeddings; no GPU). "
        "Answers are extractive from the top-4 passages; numbers must appear in those passages.",
        "",
        "## Headline",
        "",
        f"Recall@4 **{m['recall_at_4']:.0%}**. "
        f"Faithfulness (dose/number check on answered items) **{m['faithfulness']:.0%}**. "
        f"Out-of-scope refusal accuracy **{m['refusal_accuracy']:.0%}**. "
        f"In-scope refusal rate **{m['in_scope_refusal']:.0%}** (lower is better).",
        "",
        "## Retrieval and answers",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| in-scope questions | {m['in_n']} |",
        f"| out-of-scope questions | {m['oos_n']} |",
        f"| recall@4 | {m['recall_at_4']:.3f} |",
        f"| answered in-scope | {m['answered']} |",
        f"| faithfulness | {m['faithfulness']:.3f} |",
        f"| OOS refusal accuracy | {m['refusal_accuracy']:.3f} |",
        f"| in-scope refusal | {m['in_scope_refusal']:.3f} |",
        "",
        "## Next-step table",
        "",
        f"Deterministic BP × drug cases: **{table['ok']}/{table['n']}** correct actions "
        "(continue / step_up / start_step_1 / refer).",
        "",
        "## Notes",
        "",
        "* pgvector is optional. This host may not have the extension; the joblib TF-IDF index is the source of truth.",
        "* A hosted LLM can rephrase from the same passages (`reckoner_v1`) and still fails if it invents a dose.",
        "* Protocol text is an educational HEARTS / PHC adaptation, not a WHO or FMOH legal document.",
        "",
    ])


def main() -> None:
    index = build_index()
    rows = gold_set()
    QA_PATH.parent.mkdir(parents=True, exist_ok=True)
    QA_PATH.write_text(json.dumps([{k: v for k, v in r.items()} for r in rows], indent=2), encoding="utf-8")
    metrics = evaluate(rows, index)
    table = next_step_selfcheck()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(metrics, table), encoding="utf-8")
    print(f"wrote {REPORT}")
    print(f"recall@4={metrics['recall_at_4']:.2f} faith={metrics['faithfulness']:.2f} "
          f"oos_refuse={metrics['refusal_accuracy']:.2f} in_refuse={metrics['in_scope_refusal']:.2f}")
    print(f"next-step table {table['ok']}/{table['n']}")


if __name__ == "__main__":
    main()
