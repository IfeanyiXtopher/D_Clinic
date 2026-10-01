"""Builds notebooks/04_summary_eval.ipynb."""

from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).parent

SETUP = """import sys, json, warnings
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")
ROOT = Path.cwd().resolve(); ROOT = ROOT if (ROOT / "D_Clinic_Backend").exists() else ROOT.parent
sys.path.insert(0, str(ROOT / "D_Clinic_Backend"))
from llm.check import check_summary, must_keep_facts
from llm.eval_summary import AS_OF, build_eval_set, pdsqi, sloppy_text
from llm.summary import summarize_packet
from llm.template import templated_summary
from llm.gateway import GatewayResult, PROMPT_VERSION
packets = build_eval_set(200)
print(len(packets), "packets", AS_OF)"""


def main():
    nb = nbf.v4.new_notebook()
    c = []
    md = lambda s: c.append(nbf.v4.new_markdown_cell(s))
    code = lambda s: c.append(nbf.v4.new_code_cell(s))

    md("""# 04 — Patient summary evaluation

A health-worker briefing from structured data only. The packet never contains a name,
phone, address or calendar date. A model may rephrase; a post-check rejects invented
numbers or drugs and falls back to a template.

This notebook uses the same 200 packets as `make eval-summary`.""")
    code(SETUP)
    md("## 1. What the model is allowed to see")
    code("""p = packets[3]
pd.Series(p.to_prompt()).to_frame("packet")
print("hash", p.packet_hash()[:16], "case", p.case_code)
print(templated_summary(p))""")
    md("## 2. Post-check catches a hallucination")
    code("""def sloppy_gw(text):
    return GatewayResult(text, "mock", "sloppy", PROMPT_VERSION, 1, None, None, None)
p = packets[3]
bad = sloppy_text(p)
print("unchecked extras", check_summary(bad, p))
res = summarize_packet(p, complete_fn=lambda _: sloppy_gw(bad))
print("pipeline", res.check, res.fallback_used)
print(res.summary)
assert res.fallback_used and "200/130" not in res.summary""")
    md("## 3. Scores across 200 packets")
    code("""from llm.eval_summary import score_texts
rows = []
tmpl = [(p, templated_summary(p)) for p in packets]
sloppy = [(p, sloppy_text(p)) for p in packets]
pipe = []
for p in packets:
    r = summarize_packet(p, complete_fn=lambda _payload, _p=p: sloppy_gw(sloppy_text(_p)))
    pipe.append((p, r.summary))
for name, pairs in [("template", tmpl), ("sloppy", sloppy), ("pipeline", pipe)]:
    s = score_texts(name, pairs)
    rows.append({"generator": name, "factuality": s["factuality"], "omission": s["omission"],
                 "words": s["mean_words"], "pii": s["pii_rate"], "pdsqi": s["pdsqi_mean"]})
tab = pd.DataFrame(rows).set_index("generator")
ax = tab[["factuality", "pii", "pdsqi"]].plot.bar(title="Summary quality (200 packets)")
ax.set_ylim(0, 1.05); ax.legend(loc="lower right")
tab.round(3)""")
    md("## 4. PDSQI-9-style items (template)")
    code("""rubric = pd.DataFrame([pdsqi(templated_summary(p), p) for p in packets])
rubric.mean().round(3).to_frame("pass rate")""")
    md("""## 5. Live provider

If `LLM_PROVIDER` is `ollama` or `openai`, `make eval-summary` adds a live row.
This notebook does not call a network model so it stays offline after setup.""")

    nb["cells"] = c
    out = HERE / "04_summary_eval.ipynb"
    out.write_text(nbf.writes(nb), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
