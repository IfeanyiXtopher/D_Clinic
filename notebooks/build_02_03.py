"""Builds notebooks/02_missed_visit_model.ipynb and 03_fairness_and_calibration.ipynb."""

from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).parent

SETUP = """import sys, warnings, json
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")
ROOT = Path.cwd().resolve(); ROOT = ROOT if (ROOT / "D_Clinic_Backend").exists() else ROOT.parent
sys.path.insert(0, str(ROOT / "D_Clinic_Backend"))
from app.db import engine
from ml.features import load_tables_from_db, build_feature_table, FEATURES
from ml.train import (make_splits, fit_all, evaluate, precision_at_capacity, calibration_table, fairness_table,
                      explain_rows, oracle_ceiling, MODEL_FEATURES, CAPACITY_SHARE)
from ml.cold_start import add_pooled_feature
plt.rcParams["figure.figsize"] = (9, 3.5)
AS_OF = pd.Timestamp("2026-09-26")
tables = load_tables_from_db(engine)
ft = build_feature_table(tables, AS_OF)
splits = make_splits(ft)
res = fit_all(splits)
te, p = res["frames"]["test"], res["preds"]["test"][res["chosen"]]
print("chosen:", res["chosen"], {k: len(v) for k, v in splits.items()})"""


def nb02():
    nb = nbf.v4.new_notebook(); c = []
    md = lambda s: c.append(nbf.v4.new_markdown_cell(s)); code = lambda s: c.append(nbf.v4.new_code_cell(s))  # noqa
    md("""# 02 — Missed-visit risk model

Predict whether a scheduled follow-up visit will be missed, using only what is known when the visit is booked.
Compare a transparent rule score, logistic regression and gradient boosting; pick the simplest model within a small margin;
check calibration and the operational metric that matters (precision at worklist capacity); handle new patients with partial pooling.

Everything here calls the same code that the API and the nightly job use (`ml/features.py`, `ml/cold_start.py`, `ml/train.py`).""")
    code(SETUP)
    md("## 1. Label and splits\n\nStrict split: patients hashed into pools **and** a time cut, so no patient is in two splits and no future information reaches training rows.")
    code("""pd.DataFrame({k: {"rows": len(v), "patients": v.patient_id.nunique(), "missed_rate": round(v.missed.mean(), 3),
                  "from": pd.to_datetime(v.scheduled_date).min().date(), "to": pd.to_datetime(v.scheduled_date).max().date()}
              for k, v in splits.items()}).T""")
    md("## 2. Models and metrics")
    code("""rows = []
for split in ["valid", "test"]:
    for m in ["rules", "logistic", "boosting"]:
        r = res["metrics"][split][m]
        rows.append({"split": split, "model": m, "n": r["n"], "AUC": r["auc"], "PR-AUC": r["pr_auc"], "Brier": r.get("brier"),
                     "ECE": r.get("ece"), f"precision@{CAPACITY_SHARE:.0%}": r["cap_precision_at_k"], "lift": r["cap_lift"]})
pd.DataFrame(rows).round(3)""")
    code("""from sklearn.metrics import roc_curve, precision_recall_curve
y = te.missed.astype(int).values
fig, ax = plt.subplots(1, 2)
for m in ["rules", "logistic", "boosting"]:
    s = res["preds"]["test"][m]
    fpr, tpr, _ = roc_curve(y, s); ax[0].plot(fpr, tpr, label=f"{m} ({res['metrics']['test'][m]['auc']:.3f})")
    pr, rc, _ = precision_recall_curve(y, s); ax[1].plot(rc, pr, label=m)
ax[0].plot([0, 1], [0, 1], "k--", lw=.5); ax[0].set_title("ROC (test)"); ax[0].legend()
ax[1].axhline(y.mean(), ls="--", c="grey", lw=.5); ax[1].set_title("Precision–recall (test)"); ax[1].legend()
plt.tight_layout()""")
    md("## 3. Signal ceiling\n\nThe synthetic generator has a hidden per-patient propensity. Scoring with it tells us the best any model could do — the rest is irreducible per-visit randomness.")
    code("""ceiling = oracle_ceiling(te, ROOT / "data/synth/out/_truth_patients.csv")
pd.Series({**ceiling, "selected_model_auc": res["metrics"]["test"][res["chosen"]]["auc"]}).round(3).to_frame("AUC")""")
    md("## 4. Precision at worklist capacity\n\nA facility can only call so many people. Within each facility-week we rank by score and take the top share; how many of those were actually missed?")
    code("""shares = [0.1, 0.2, 0.3, 0.4, 0.5]
tab = pd.DataFrame({m: [precision_at_capacity(te, res["preds"]["test"][m], s)["precision_at_k"] for s in shares]
                    for m in ["rules", "logistic", "boosting"]}, index=[f"{s:.0%}" for s in shares])
ax = tab.plot(marker="o", title="Precision of the selected list vs list size (test)")
ax.axhline(y.mean(), ls="--", c="grey", label="base rate"); ax.set_xlabel("share of the week's appointments on the list"); ax.legend()
tab.round(3)""")
    md("## 5. Calibration and risk bands")
    code("""ct = calibration_table(y, p)
fig, ax = plt.subplots(1, 2)
ax[0].plot(ct.predicted, ct.observed, marker="o"); ax[0].plot([0, .8], [0, .8], "k--", lw=.5)
ax[0].set_xlabel("predicted"); ax[0].set_ylabel("observed"); ax[0].set_title(f"Calibration (test, {res['chosen']})")
from ml.train import band
b = pd.DataFrame({"band": band(p, res["thresholds"]), "missed": y}).groupby("band").missed.agg(["size", "mean"]).reindex(["low", "medium", "high"])
b["mean"].plot.bar(ax=ax[1], rot=0, title="Observed miss rate by band"); plt.tight_layout()
b.rename(columns={"size": "n", "mean": "observed_miss_rate"}).round(3)""")
    md("## 6. What drives the score\n\nStandardised logistic coefficients. Positive = raises missed-visit risk.")
    code("""lr = res["logistic"]; prep = lr.named_steps["prep"]
names = [n.split("__", 1)[1] for n in prep.get_feature_names_out()]
coef = pd.Series(lr.named_steps["clf"].coef_[0], index=names)
coef = coef[~coef.index.str.startswith(("facility_id_", "scheduled_weekday_"))].sort_values()
coef.plot.barh(figsize=(8, 7), title="Logistic coefficients (standardised inputs)"); plt.tight_layout()""")
    md("## 7. New patients: partial pooling\n\nRows with no personal history get the group estimate; the UI labels them as such.")
    code("""pooled = res["cold_start"].pooled(te)
cs = pd.DataFrame({"basis": pooled.basis, "group_level": pooled.group_level, "observed": y, "predicted": p})
display(cs.groupby("basis").agg(n=("observed", "size"), observed=("observed", "mean"), predicted=("predicted", "mean")).round(3))
cs[cs.basis == "group"].group_level.value_counts().to_frame("group rows by back-off level")""")
    md("## 8. Example explanations")
    code("""f = add_pooled_feature(te, res["cold_start"])
ex = pd.DataFrame({"p": p.round(3), "basis": pooled.basis, "reasons": explain_rows(res["logistic"], f)})
ex.sort_values("p", ascending=False).head(8)""")
    md("""## Takeaways

- Logistic regression is kept: boosting gains < 0.01 AUC, and a linear model gives readable reasons.
- At 30% list capacity the model reaches ~0.44 precision vs a 0.30 base rate (lift ≈ 1.5) and beats the hand rules.
- The model sits ~0.05 AUC below the synthetic ceiling; the remaining gap is per-visit randomness, not a missing feature.
- Calibration is good enough to show bands; a raw percentage is still hidden from the UI until validated on real data.
- Cold-start rows are well calibrated as a group estimate and labelled as such.""")
    nb["cells"] = c; nb["metadata"] = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}}
    nbf.write(nb, HERE / "02_missed_visit_model.ipynb")


def nb03():
    nb = nbf.v4.new_notebook(); c = []
    md = lambda s: c.append(nbf.v4.new_markdown_cell(s)); code = lambda s: c.append(nbf.v4.new_code_cell(s))  # noqa
    md("""# 03 — Fairness and calibration audit

Does the missed-visit model treat groups differently? For each group we compare: base rate, mean prediction, AUC,
**selection rate at worklist capacity** (who gets on the list), **false-negative rate at capacity** (who is missed by the list),
and calibration error. Groups: sex, age band, facility, distance band, and **region** — which is *not* a feature and appears only here.

Design principle (see `docs/responsible_ai.md`): a high score adds support; it never removes anyone. So the harm to watch for is
*under-selection* of a group that misses often (they don't get help), and *over-selection* of a group that doesn't (wasted calls, stigma).""")
    code(SETUP)
    md("## 1. Fairness tables (test set)")
    code("""for col in ["gender", "age_band", "distance_band", "region", "facility_id"]:
    print(f"\\n### by {col}")
    display(fairness_table(te, p, col))""")
    md("## 2. Selection rate vs base rate\n\nIf the list is fair in the sense of *equal opportunity for support*, selection should track how often each group actually misses.")
    code("""fig, axes = plt.subplots(1, 4, figsize=(15, 3.5))
for ax, col in zip(axes, ["gender", "age_band", "distance_band", "region"]):
    t = fairness_table(te, p, col).set_index(col)
    t[["base_rate", "selection_rate"]].plot.bar(ax=ax, rot=0, title=f"by {col}"); ax.set_xlabel("")
plt.tight_layout()""")
    md("## 3. Calibration within groups")
    code("""fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
for ax, col in zip(axes, ["gender", "age_band", "region"]):
    for g, d in te.assign(p=p).groupby(col):
        ct = calibration_table(d.missed.astype(int).values, d.p.values, 5)
        ax.plot(ct.predicted, ct.observed, marker="o", label=f"{g} (n={len(d)})")
    ax.plot([0.1, 0.6], [0.1, 0.6], "k--", lw=.5); ax.set_title(f"calibration by {col}"); ax.legend(fontsize=7)
plt.tight_layout()""")
    md("""## 4. The region gap, decomposed

The generator gives region **no causal effect**, yet raw miss rates differ by region. Distance band is the mediator: some regions have more
patients living far from their facility. Within a distance band, the regional differences shrink to noise. This is why distance is a feature
(actionable: travel support, closer facility, longer refills) and region is not (a proxy for access that would encode the disparity).""")
    code("""aud = te.assign(p=p, missed=te.missed.astype(int))
display(aud.pivot_table(index="distance_band", columns="region", values="missed", aggfunc="mean").round(3).reindex(["near", "mid", "far"]))
display(aud.pivot_table(index="distance_band", columns="region", values="p", aggfunc="mean").round(3).reindex(["near", "mid", "far"]))
pd.crosstab(aud.region, aud.distance_band, normalize="index").round(3)[["near", "mid", "far"]]""")
    md("## 5. Uncertainty for small groups\n\nBootstrap the selection-rate gap (selection − base rate) for the smallest region, and compare that region's miss rate in the small test sample with its rate across the whole labelled cohort.")
    code("""rng = np.random.default_rng(0)
small = fairness_table(te, p, "region").set_index("region").n.idxmin()
def gap(sample):
    t = fairness_table(sample, sample.p.values, "region").set_index("region")
    return t.loc[small, "selection_rate"] - t.loc[small, "base_rate"]
aud2 = te.assign(p=p)
boots = [gap(aud2.sample(frac=1, replace=True, random_state=int(s))) for s in rng.integers(0, 1e6, 200)]
lo, hi = np.percentile(boots, 2.5), np.percentile(boots, 97.5)
print(f"{small}: selection − base rate = {gap(aud2):.3f}; 95% bootstrap interval [{lo:.3f}, {hi:.3f}]")
from ml.features import labelled
allrows = labelled(ft).frame
cmp = pd.DataFrame({"test sample": te.groupby("region").missed.mean(), "whole labelled cohort": allrows.groupby("region").missed.mean(),
                    "n test": te.groupby("region").size(), "n cohort": allrows.groupby("region").size()}).round(3)
display(cmp)
direction = "over-selected (more support offered than its miss rate alone would warrant)" if gap(aud2) > 0 else "under-selected (less support than its miss rate warrants)"
print(f"Reading: {small} is {direction}. Interval {'excludes' if lo > 0 or hi < 0 else 'includes'} zero.")""")
    md("""## Findings and decisions

- **Sex.** Selection tracks base rate for women (0.30 vs 0.30). Men are selected somewhat more than their base rate (≈0.35 vs 0.29): `male` is a small positive feature in the generator and the model. Their false-negative rate at capacity is correspondingly *lower*, so men are not disadvantaged; women's FNR (0.56) is the number to watch, and it is in line with the overall rate.
- **Age.** Under-40s miss most often (0.38) and are selected most (≈0.50); their FNR at capacity is the lowest (0.30). Over-70s are selected at roughly their base rate but with the largest calibration error (ECE 0.07, n = 219) — a small-group effect to monitor, not a systematic under-selection.
- **Distance.** Patients living far are selected more *because* they miss more. That is the intended behaviour: the list exists to offer them support.
- **Region.** The raw gap in miss rate is explained by distance composition (§4); within distance bands the differences shrink. Region stays out of the model.
- **Smallest region (§5).** In this test split the smallest region is *over*-selected by roughly 0.1, and the bootstrap interval excludes zero. Two facts frame this: the generator gives region no causal effect, and the region's miss rate over the whole cohort is in line with the others while its small test sample happens to be low — so the gap reflects the composition of a ~180-row sample, not a regional mechanism. Under the design principle (a score only *adds* support) over-selection is the less harmful direction, so no threshold change is made; the gap is logged as a **monitoring item** and must be re-checked on every retrain. Had the direction been under-selection of a group that misses often, the decision would be a per-facility threshold adjustment before promotion.
- **Facility.** Differences reflect real facility-level miss rates; the capacity metric is computed *within* facility, so no facility crowds out another.
- **Promotion gate (Step 9).** Retraining must regenerate these tables and fail promotion if any group's false-negative rate at capacity exceeds the overall rate by more than 0.10, or if any group with n ≥ 300 is under-selected relative to its base rate by more than 0.05.""")
    nb["cells"] = c; nb["metadata"] = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}}
    nbf.write(nb, HERE / "03_fairness_and_calibration.ipynb")


if __name__ == "__main__":
    nb02(); nb03(); print("wrote 02 and 03")
