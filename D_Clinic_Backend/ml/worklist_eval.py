"""Replay evaluation of worklist strategies.

Question: if a facility can only call N overdue patients this week, does ranking
them by predicted miss risk bring more patients back than the usual
"longest overdue first" list?

Design
------
* Replay week by week over the **test period** using only **test-pool patients**
  (the model never saw them). Capacity is scaled to the pool share so the
  replay is as tight as real life: 20 calls/day x 5 days x 25% = 25 per facility-week.
* At each Monday the same eligibility rules run (:mod:`ml.worklist`), then each
  strategy picks its top-N: ``risk`` (model), ``days_overdue`` (status quo),
  ``random`` (floor), ``oracle`` (ranks by the generator's hidden propensity; ceiling).
* Two outcome views:

  1. **Counterfactual uplift** (synthetic cohorts only). The generator's return
     behaviour is a known function of the hidden propensity, so for every selected
     patient we know P(return | called) and P(return | not called). The mean
     difference is the *expected extra returns per call* - the quantity a program
     actually buys with its call capacity.
  2. **Observational**. Among selected patients who *were* called that week in the
     data, the share that returned within 15 days (Simple's call-effectiveness
     metric). Reported for transparency; it is confounded because the model
     deliberately selects harder patients, who return less even after a call.

Run: ``python -m ml.worklist_eval`` (DB) or ``--csv data/synth/out``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for data.synth.generate
from data.synth.generate import p_return_after_call, p_return_no_call  # noqa: E402

from app.settings import REPO_ROOT, settings  # noqa: E402
from ml.features import build_feature_table, load_tables_from_csv, load_tables_from_db  # noqa: E402
from ml.predict import score_frame  # noqa: E402
from ml.train import TEST_START, assign_pool, load_artifact  # noqa: E402
from ml.worklist import WorklistConfig, overdue_candidates, rank_candidates  # noqa: E402

REPORT_PATH = REPO_ROOT / "docs" / "eval_reports" / "worklist.md"
STRATEGIES = ["days_overdue", "random", "risk", "oracle"]
WEEKLY_CAPACITY = 25  # 20/day x 5 days x 0.25 test-pool share
PROGRAM_END = pd.Timestamp("2026-09-25")


def replay(tables: dict[str, pd.DataFrame], artifact: dict, truth: pd.Series, start: pd.Timestamp = TEST_START,
           end: pd.Timestamp = PROGRAM_END - pd.Timedelta(days=15), capacity: int = WEEKLY_CAPACITY,
           pool: str | None = "test", protected_share: float = 0.25, seed: int = 0) -> pd.DataFrame:
    """One row per (week, facility, strategy, selected patient)."""
    patients = tables["patients"]
    if pool:
        keep = patients.patient_id[assign_pool(patients.patient_id) == pool]
        tables = {k: (v[v.patient_id.isin(keep)] if "patient_id" in v.columns else v) for k, v in tables.items()}
    ft = build_feature_table(tables, PROGRAM_END)
    scores = score_frame(ft.frame, artifact).set_index("appointment_id")[["p_missed", "band", "basis"]]

    bps = tables["blood_pressures"].assign(recorded_at=lambda x: pd.to_datetime(x.recorded_at))
    calls = tables["call_results"].assign(device_created_at=lambda x: pd.to_datetime(x.device_created_at))
    rows = []
    mondays = pd.date_range(start, end, freq="W-MON")
    for wk, monday in enumerate(mondays):
        cands = overdue_candidates(tables, monday, WorklistConfig())
        cands = cands.join(scores, on="appointment_id")
        cands["theta"] = cands.patient_id.astype(str).map(truth)
        for fac, cf in cands.groupby("facility_id"):
            for strat in STRATEGIES:
                cfg = WorklistConfig(capacity=capacity, protected_share=protected_share, seed=seed + wk,
                                     rank_by="risk" if strat == "oracle" else strat)
                c = cf.copy()
                if strat == "oracle":
                    c["p_missed"] = c.theta  # rank by hidden truth
                r = rank_candidates(c, cfg)
                sel = r[r.selected].copy()
                if sel.empty:
                    continue
                sel["strategy"] = strat
                sel["week"] = monday
                # observational outcome: called this week? returned within 15 days of the call?
                wk_calls = calls[(calls.device_created_at >= monday) & (calls.device_created_at < monday + pd.Timedelta(days=7))]
                first_call = wk_calls.sort_values("device_created_at").groupby("appointment_id").device_created_at.first()
                sel["called_at"] = sel.appointment_id.map(first_call)
                sel["called"] = sel.called_at.notna()
                ret = []
                for pid, ca in zip(sel.patient_id, sel.called_at):
                    if pd.isna(ca):
                        ret.append(np.nan)
                    else:
                        b = bps[(bps.patient_id == pid) & (bps.recorded_at > ca) & (bps.recorded_at <= ca + pd.Timedelta(days=15))]
                        ret.append(float(len(b) > 0))
                sel["returned_15d"] = ret
                # counterfactual
                sel["p_call"] = sel.theta.map(p_return_after_call)
                sel["p_no_call"] = sel.theta.map(p_return_no_call)
                sel["uplift"] = sel.p_call - sel.p_no_call
                rows.append(sel[["week", "facility_id", "strategy", "patient_id", "appointment_id", "rank", "protected_slot",
                                 "p_missed", "band", "basis", "days_overdue", "uncontrolled", "has_phone", "theta",
                                 "called", "returned_15d", "p_call", "p_no_call", "uplift"]])
    return pd.concat(rows, ignore_index=True)


def summarise(rep: pd.DataFrame) -> pd.DataFrame:
    g = rep.groupby("strategy")
    out = pd.DataFrame({
        "selected": g.size(),
        "expected_returns_per_100_calls": 100 * g.p_call.mean(),
        "expected_returns_no_call_per_100": 100 * g.p_no_call.mean(),
        "extra_returns_per_100_calls": 100 * g.uplift.mean(),
        "mean_theta": g.theta.mean(),
        "share_uncontrolled": g.uncontrolled.mean(),
        "share_cold_start": g.basis.apply(lambda s: (s == "group").mean()),
        "mean_days_overdue": g.days_overdue.mean(),
        "actually_called_share": g.called.mean(),
        "obs_return_15d_among_called": g.returned_15d.mean(),
        "obs_called_n": g.returned_15d.count(),
    })
    return out.loc[[s for s in STRATEGIES if s in out.index]]


def bootstrap_diff(rep: pd.DataFrame, a: str = "risk", b: str = "days_overdue", n: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """Facility-week block bootstrap of the difference in mean uplift (per 100 calls)."""
    rng = np.random.default_rng(seed)
    blocks = rep.groupby(["week", "facility_id"])
    keys = list(blocks.groups)
    per_block = {k: (blocks.get_group(k).query("strategy == @a").uplift.mean(), blocks.get_group(k).query("strategy == @b").uplift.mean()) for k in keys}
    diffs = np.array([pa - pb for pa, pb in per_block.values()]) * 100
    diffs = diffs[~np.isnan(diffs)]
    boots = [rng.choice(diffs, len(diffs)).mean() for _ in range(n)]
    return float(diffs.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def overlap(rep: pd.DataFrame, a: str = "risk", b: str = "days_overdue") -> float:
    """Share of `a`'s selections also chosen by `b`, averaged over facility-weeks."""
    vals = []
    for _, blk in rep.groupby(["week", "facility_id"]):
        sa = set(blk[blk.strategy == a].patient_id); sb = set(blk[blk.strategy == b].patient_id)
        if sa:
            vals.append(len(sa & sb) / len(sa))
    return float(np.mean(vals))


def _observational_note(s: pd.DataFrame) -> str:
    risk = s.loc["risk"]
    others = s.drop(index=["risk", "oracle"], errors="ignore").obs_return_15d_among_called.dropna()
    if pd.isna(risk.obs_return_15d_among_called) or others.empty:
        return ("Too few of the selected patients were actually called in the data for an observational comparison; "
                "the counterfactual view above is the one that matters.")
    direction = "higher" if risk.obs_return_15d_among_called >= others.max() else "not higher"
    return (f"Among patients who were actually called, the risk-ranked selection's return-within-15-days rate "
            f"({risk.obs_return_15d_among_called:.0%}, n={int(risk.obs_called_n)}) is {direction} than the alternatives "
            f"({', '.join(f'{k} {v:.0%}' for k, v in others.items())}). Read this with care: the model deliberately selects "
            "patients who return less on their own, so raw return rate can penalise a list that is doing its job, and the "
            "counts are small. In a real deployment the worklist is judged with a randomised or stepped-wedge rollout, not "
            "with this metric alone. Strategies whose selections were never called in the data show n/a.")


def write_report(summary: pd.DataFrame, rep: pd.DataFrame, diff: tuple[float, float, float], ovl: float,
                 n_weeks: int, capacity: int, path: Path = REPORT_PATH) -> None:
    s = summary
    risk, dov = s.loc["risk"], s.loc["days_overdue"]
    rel = (risk.extra_returns_per_100_calls / dov.extra_returns_per_100_calls - 1) * 100
    lines = [
        "# Worklist replay evaluation",
        "",
        f"Auto-generated by `python -m ml.worklist_eval`. Test-pool patients only, {n_weeks} weekly snapshots from "
        f"{rep.week.min():%Y-%m-%d} to {rep.week.max():%Y-%m-%d}, capacity {capacity} calls per facility-week, "
        f"25% of slots protected for uncontrolled BP, same eligibility rules for every strategy.",
        "",
        "## Headline",
        "",
        f"Ranking by predicted risk yields **{risk.extra_returns_per_100_calls:.1f} extra returns per 100 calls** versus "
        f"**{dov.extra_returns_per_100_calls:.1f}** for the longest-overdue-first list (**{rel:+.0f}%**). "
        f"Facility-week bootstrap of the difference: {diff[0]:+.1f} [{diff[1]:+.1f}, {diff[2]:+.1f}] per 100 calls. "
        f"The oracle that ranks by the hidden propensity reaches {s.loc['oracle'].extra_returns_per_100_calls:.1f}; "
        f"random selection {s.loc['random'].extra_returns_per_100_calls:.1f}.",
        "",
        f"The two lists agree on only {ovl:.0%} of patients in a typical facility-week: the model is not a re-labelling of days overdue.",
        "",
        "## Strategies",
        "",
        "| strategy | selected | expected returns /100 calls | expected returns if not called /100 | **extra returns /100 calls** | mean hidden propensity | share uncontrolled | share cold-start | mean days overdue |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, r in s.iterrows():
        lines.append(f"| {name} | {int(r.selected)} | {r.expected_returns_per_100_calls:.1f} | {r.expected_returns_no_call_per_100:.1f} | "
                     f"**{r.extra_returns_per_100_calls:.1f}** | {r.mean_theta:+.2f} | {r.share_uncontrolled:.0%} | {r.share_cold_start:.0%} | {r.mean_days_overdue:.0f} |")
    lines += [
        "",
        "How to read this: a call to a patient who would have come back anyway buys nothing. The `extra returns` column is the "
        "counterfactual gain a program gets from spending a call on that patient. It can be computed here only because the "
        "cohort is synthetic and the return mechanism is known (`data/synth/generate.py::p_return_after_call / p_return_no_call`).",
        "",
        "## Observational view (Simple's call-effectiveness metric)",
        "",
        "| strategy | share of selected actually called that week | returned within 15 days of call (among called) | n called |",
        "|---|---:|---:|---:|",
    ]
    for name, r in s.iterrows():
        obs = "n/a" if pd.isna(r.obs_return_15d_among_called) else f"{r.obs_return_15d_among_called:.1%}"
        lines.append(f"| {name} | {r.actually_called_share:.0%} | {obs} | {int(r.obs_called_n)} |")
    lines += ["", _observational_note(s)]
    cs_risk, cs_dov = risk.share_cold_start, dov.share_cold_start
    lines += [
        "",
        "## Side effects worth knowing",
        "",
        f"* **Cold-start patients get fewer calls under risk ranking** ({cs_risk:.0%} of selections vs {cs_dov:.0%} under "
        "longest-overdue-first). A patient with no history is scored near the group average and rarely reaches the top of the "
        "list. A program that wants to reach newly registered patients early should protect slots for them, the same way "
        "uncontrolled BP is protected here. This is a policy choice and is exposed as configuration, not hidden in the model.",
        f"* Protected slots guarantee at least 25% of each list goes to uncontrolled BP; in practice the risk list carries "
        f"{risk.share_uncontrolled:.0%} (random {s.loc['random'].share_uncontrolled:.0%}), because uncontrolled BP is itself a risk signal.",
        f"* Longest-overdue-first spends its capacity on patients a mean {dov.mean_days_overdue:.0f} days overdue; risk ranking on "
        f"{risk.mean_days_overdue:.0f} days. The status-quo list mostly reaches people who left months ago.",
        "",
        "## Caveats",
        "",
        "* Weekly snapshots ignore within-week state changes (a Monday call moves a patient into the 15-day cooldown).",
        "* `random` and `days_overdue` respect the same phone-first and protected-slot rules, so the comparison isolates ranking.",
        "* Synthetic data: effect sizes are properties of the generator, not of any real program. The evaluation code is the deliverable; "
        "the numbers show it works end to end.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="generator output dir instead of the database")
    ap.add_argument("--truth", default=str(settings.synth_out_dir / "_truth_patients.csv"))
    ap.add_argument("--capacity", type=int, default=WEEKLY_CAPACITY)
    ap.add_argument("--pool", default="test", help="patient pool to replay (test|valid|train|all)")
    ap.add_argument("--report", default=str(REPORT_PATH))
    args = ap.parse_args()

    if args.csv:
        tables = load_tables_from_csv(args.csv)
    else:
        from app.db import engine
        tables = load_tables_from_db(engine)
    truth = pd.read_csv(args.truth).set_index("patient_id").theta
    artifact = load_artifact()
    rep = replay(tables, artifact, truth, capacity=args.capacity, pool=None if args.pool == "all" else args.pool)
    summary = summarise(rep)
    diff = bootstrap_diff(rep)
    ovl = overlap(rep)
    pd.set_option("display.width", 200)
    print(summary.round(3).to_string())
    print(f"\nrisk - days_overdue extra returns per 100 calls: {diff[0]:+.2f} [{diff[1]:+.2f}, {diff[2]:+.2f}]   overlap {ovl:.0%}")
    write_report(summary, rep, diff, ovl, rep.week.nunique(), args.capacity, Path(args.report))
    print("report:", args.report)


if __name__ == "__main__":
    main()
