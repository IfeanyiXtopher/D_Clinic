"""Train and evaluate the missed-visit risk model.

Run:  python -m ml.train            (reads the database, writes an artifact + report)
      python -m ml.train --csv ../data/synth/out

Splits (strict): patients are hashed into pools (train 60% / valid 15% / test 25%)
**and** time is cut: train uses appointments scheduled before ``VALID_START``,
valid the window ``[VALID_START, TEST_START)``, test ``>= TEST_START``. No patient
appears in two splits, and no future information reaches the training rows.

Models: rule score (transparent baseline), logistic regression, histogram
gradient boosting. Selection rule: keep logistic regression unless boosting
beats it on validation AUC by more than ``SELECTION_MARGIN``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from ml.cold_start import ColdStartModel, add_pooled_feature
from ml.features import BINARY_FEATURES, CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES, FeatureTable, build_feature_table, labelled

MODEL_FEATURES = FEATURES + ["pooled_miss_rate"]
NUMERIC_MODEL = NUMERIC_FEATURES + ["pooled_miss_rate"]

VALID_START = pd.Timestamp("2026-03-01")
TEST_START = pd.Timestamp("2026-06-01")
POOL_SPLIT = (0.60, 0.15, 0.25)
SELECTION_MARGIN = 0.01
CAPACITY_SHARE = 0.30  # the worklist can hold ~30% of a facility-week's appointments
MODEL_VERSION = "missed_visit_v1"
ARTIFACT_DIR = Path(__file__).parent / "artifacts"
REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "eval_reports" / "missed_visit_model.md"

REASON_LABELS = {
    "prior_miss_rate": "history of missed visits",
    "pooled_miss_rate": "high estimated miss rate (own history and similar patients)",
    "consecutive_misses": "missed the last visit(s) in a row",
    "prior_missed": "number of past missed visits",
    "lead_days": "long gap until the visit",
    "distance_band_far": "lives far from the facility",
    "distance_band_mid": "lives some distance from the facility",
    "facility_prior_miss_rate": "facility has a high miss rate",
    "uncontrolled": "blood pressure not controlled",
    "n_protocol_drugs": "several BP medicines",
    "drug_changed_at_booking": "medicines just changed",
    "male": "male",
    "age_band_<40": "under 40",
    "age_band_70+": "70 or older",
    "diabetic": "also has diabetes",
    "rainy_season": "visit falls in the rainy season",
    "last_call_result_removed_from_overdue_list": "previously removed from the overdue list",
    "last_call_result_remind_to_call_later": "asked to be called back before",
    "months_in_program": "time in the program",
    "systolic": "systolic blood pressure",
    "systolic_change": "recent change in systolic BP",
    "last_gap_days": "gap since previous visit",
    "prior_calls": "has needed overdue calls before",
}


# ----------------------------------------------------------------------------- splits


def assign_pool(patient_ids: pd.Series, seed: int = 42) -> pd.Series:
    """Stable patient → pool assignment by hashing the id with a seed."""
    def h(pid: str) -> float:
        return int(hashlib.sha256(f"{seed}:{pid}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF

    u = patient_ids.map(h)
    tr, va, _ = POOL_SPLIT
    return pd.Series(np.select([u < tr, u < tr + va], ["train", "valid"], default="test"), index=patient_ids.index)


def make_splits(ft: FeatureTable, seed: int = 42) -> dict[str, pd.DataFrame]:
    f = labelled(ft).frame.copy()
    f["pool"] = assign_pool(f.patient_id, seed)
    sd = pd.to_datetime(f.scheduled_date)
    return {
        "train": f[(f.pool == "train") & (sd < VALID_START)].reset_index(drop=True),
        "valid": f[(f.pool == "valid") & (sd >= VALID_START) & (sd < TEST_START)].reset_index(drop=True),
        "test": f[(f.pool == "test") & (sd >= TEST_START)].reset_index(drop=True),
    }


# ----------------------------------------------------------------------------- models


def rule_score(X: pd.DataFrame) -> np.ndarray:
    """Transparent points-based baseline (0–8). Mirrors the rules a nurse could apply by hand."""
    pts = np.zeros(len(X))
    pts += 2 * (X.prior_miss_rate.fillna(0.25) > 0.30)
    pts += 1 * (X.prior_miss_rate.fillna(0.25).between(0.15, 0.30, inclusive="left"))
    pts += 2 * (X.consecutive_misses >= 1)
    pts += 1 * (X.lead_days > 35)
    pts += 1 * (X.lead_days > 60)
    pts += 1 * (X.distance_band == "far")
    pts += 1 * (X.uncontrolled == 1)
    return pts


def _preprocessor(one_hot: bool) -> ColumnTransformer:
    num = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    if one_hot:
        cat = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    else:
        cat = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    return ColumnTransformer([
        ("num", num, NUMERIC_MODEL),
        ("bin", "passthrough", BINARY_FEATURES),
        ("cat", cat, CATEGORICAL_FEATURES),
    ])


def make_logistic() -> Pipeline:
    return Pipeline([("prep", _preprocessor(one_hot=True)),
                     ("clf", LogisticRegression(C=0.5, max_iter=2000, class_weight=None))])


def make_boosting(seed: int = 42) -> Pipeline:
    n_num = len(NUMERIC_MODEL) + len(BINARY_FEATURES)
    cat_mask = [False] * n_num + [True] * len(CATEGORICAL_FEATURES)
    clf = HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=400, max_leaf_nodes=15, min_samples_leaf=40,
        l2_regularization=1.0, early_stopping=True, validation_fraction=0.15, random_state=seed,
        categorical_features=cat_mask,
    )
    return Pipeline([("prep", _preprocessor(one_hot=False)), ("clf", clf)])


# ----------------------------------------------------------------------------- metrics


def _select_at_capacity(f: pd.DataFrame, score_col: str, share: float) -> pd.Series:
    """Boolean mask: top ``share`` of appointments within each facility-week by score."""
    f = f.copy()
    f["week"] = pd.to_datetime(f.scheduled_date).dt.to_period("W").astype(str)
    g = f.groupby(["facility_id", "week"])
    rank = g[score_col].rank(method="first", ascending=False)
    k = np.ceil(g[score_col].transform("size") * share)
    return rank <= k


def precision_at_capacity(frame: pd.DataFrame, score: np.ndarray, share: float = CAPACITY_SHARE) -> dict:
    """Rank appointments within each facility-week, select the top ``share``, measure how many were missed."""
    f = frame[["facility_id", "scheduled_date", "missed"]].copy()
    f["score"] = score
    sel = f[_select_at_capacity(f, "score", share)]
    return {
        "capacity_share": share,
        "selected": int(len(sel)),
        "selected_share": float(len(sel) / len(f)),
        "precision_at_k": float(sel.missed.mean()),
        "recall_at_k": float(sel.missed.sum() / max(f.missed.sum(), 1)),
        "base_rate": float(f.missed.mean()),
        "lift": float(sel.missed.mean() / max(f.missed.mean(), 1e-9)),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    q = pd.qcut(p, bins, duplicates="drop")
    t = pd.DataFrame({"y": y, "p": p, "bin": q}).groupby("bin", observed=True).agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"))
    return t.reset_index(drop=True)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    t = calibration_table(y, p, bins)
    return float((t.n / t.n.sum() * (t.predicted - t.observed).abs()).sum())


def evaluate(frame: pd.DataFrame, p: np.ndarray, is_probability: bool = True) -> dict:
    y = frame.missed.astype(int).values
    out = {
        "n": int(len(y)),
        "base_rate": float(y.mean()),
        "auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
    }
    if is_probability:
        out["brier"] = float(brier_score_loss(y, p))
        out["log_loss"] = float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)))
        out["ece"] = expected_calibration_error(y, p)
    out.update({f"cap_{k}": v for k, v in precision_at_capacity(frame, p).items()})
    return out


def fairness_table(frame: pd.DataFrame, p: np.ndarray, group_col: str, share: float = CAPACITY_SHARE) -> pd.DataFrame:
    """Per-group base rate, mean prediction, AUC, selection rate at capacity and false-negative rate."""
    f = frame.copy()
    f["p"] = p
    f["selected"] = _select_at_capacity(f, "p", share)
    rows = []
    for g, d in f.groupby(group_col, observed=True):
        y = d.missed.astype(int)
        rows.append({
            group_col: g, "n": len(d), "base_rate": y.mean(), "mean_pred": d.p.mean(),
            "auc": roc_auc_score(y, d.p) if y.nunique() == 2 else np.nan,
            "selection_rate": d.selected.mean(),
            "fnr_at_capacity": ((~d.selected) & (y == 1)).sum() / max((y == 1).sum(), 1),
            "ece": expected_calibration_error(y.values, d.p.values, 5),
        })
    return pd.DataFrame(rows).round(3)


# ----------------------------------------------------------------------------- reasons


REASON_EXCLUDE_PREFIXES = ("prior_appointments", "months_in_program", "scheduled_weekday_", "last_call_result_none",
                           "facility_id_", "diastolic", "last_gap_days")


def explain_rows(lr: Pipeline, X: pd.DataFrame, top: int = 3, min_contribution: float = 0.05) -> list[list[str]]:
    """Top risk-raising contributions of the logistic model, in plain language.

    Only features with a *positive* coefficient are eligible, so a reason always means
    "this factor is present / elevated and it raises risk". Exposure counts and facility
    identity are excluded because they are not actionable explanations for a health worker.
    """
    prep, clf = lr.named_steps["prep"], lr.named_steps["clf"]
    Xt = prep.transform(X[MODEL_FEATURES])
    names = [n.split("__", 1)[1] for n in prep.get_feature_names_out()]
    coef = clf.coef_[0]
    eligible = np.array([c > 0 and not n.startswith(REASON_EXCLUDE_PREFIXES) for n, c in zip(names, coef)])
    contrib = np.where(eligible, Xt * coef, -np.inf)
    out = []
    for row in contrib:
        idx = np.argsort(-row)[:top]
        out.append([REASON_LABELS.get(names[i], names[i].replace("_", " ")) for i in idx if row[i] > min_contribution])
    return out


# ----------------------------------------------------------------------------- training


def fit_all(splits: dict[str, pd.DataFrame], seed: int = 42) -> dict:
    cs = ColdStartModel().fit(splits["train"])
    tr = add_pooled_feature(splits["train"], cs)
    va = add_pooled_feature(splits["valid"], cs)
    te = add_pooled_feature(splits["test"], cs)
    y_tr = tr.missed.astype(int)

    lr = make_logistic().fit(tr[MODEL_FEATURES], y_tr)
    gb = make_boosting(seed).fit(tr[MODEL_FEATURES], y_tr)

    preds = {}
    for name, d in [("train", tr), ("valid", va), ("test", te)]:
        preds[name] = {
            "rules": rule_score(d[MODEL_FEATURES]),
            "logistic": lr.predict_proba(d[MODEL_FEATURES])[:, 1],
            "boosting": gb.predict_proba(d[MODEL_FEATURES])[:, 1],
        }
    metrics = {split: {m: evaluate(d, preds[split][m], is_probability=(m != "rules"))
                       for m in ["rules", "logistic", "boosting"]}
               for split, d in [("train", tr), ("valid", va), ("test", te)]}

    chosen = "boosting" if metrics["valid"]["boosting"]["auc"] > metrics["valid"]["logistic"]["auc"] + SELECTION_MARGIN else "logistic"
    model = gb if chosen == "boosting" else lr
    p_train = preds["train"][chosen]
    thresholds = {"medium": float(np.quantile(p_train, 0.50)), "high": float(np.quantile(p_train, 0.80))}
    return {"cold_start": cs, "logistic": lr, "boosting": gb, "chosen": chosen, "model": model,
            "metrics": metrics, "thresholds": thresholds, "frames": {"train": tr, "valid": va, "test": te}, "preds": preds}


def band(p: np.ndarray, thresholds: dict) -> np.ndarray:
    return np.select([p >= thresholds["high"], p >= thresholds["medium"]], ["high", "medium"], default="low")


def save_artifact(result: dict, path: Path = ARTIFACT_DIR / f"{MODEL_VERSION}.joblib") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "chosen": result["chosen"],
        "model": result["model"],
        "reason_model": result["logistic"],
        "cold_start": result["cold_start"],
        "thresholds": result["thresholds"],
        "features": MODEL_FEATURES,
        "metrics": result["metrics"],
    }, path)
    return path


def load_artifact(path: Path = ARTIFACT_DIR / f"{MODEL_VERSION}.joblib") -> dict:
    return joblib.load(path)


def oracle_ceiling(test: pd.DataFrame, truth_path: Path | None) -> dict | None:
    """AUC achievable with the generator's hidden per-patient propensity. Synthetic data only.

    This is the honest upper bound: no model trained on observable history can beat what the
    latent truth itself achieves, because each appointment still has irreducible randomness.
    """
    if truth_path is None or not Path(truth_path).exists():
        return None
    truth = pd.read_csv(truth_path).set_index("patient_id").theta
    theta = test.patient_id.astype(str).map(truth)  # DB returns UUID objects; the CSV has strings
    if theta.isna().any():
        return None
    y = test.missed.astype(int)
    zone = test.distance_band.map({"near": 0.0, "mid": 0.25, "far": 0.60}).fillna(0)
    approx = 0.9 * theta + 0.55 * (test.lead_days > 35) + 0.45 * (test.lead_days > 60) + zone + 0.3 * test.consecutive_misses.clip(upper=2)
    return {"theta_only_auc": float(roc_auc_score(y, theta)), "theta_plus_known_effects_auc": float(roc_auc_score(y, approx))}


def write_report(result: dict, splits: dict[str, pd.DataFrame], path: Path = REPORT_PATH, truth_path: Path | None = None) -> None:
    m = result["metrics"]
    te = result["frames"]["test"]
    p = result["preds"]["test"][result["chosen"]]
    ceiling = oracle_ceiling(te, truth_path)

    def row(split: str, model: str) -> str:
        r = m[split][model]
        prob = "" if model == "rules" else f" {r['brier']:.3f} | {r['ece']:.3f} |"
        prob = prob if model != "rules" else " – | – |"
        return (f"| {split} | {model} | {r['n']:,} | {r['base_rate']:.3f} | {r['auc']:.3f} | {r['pr_auc']:.3f} |"
                f"{prob} {r['cap_precision_at_k']:.3f} | {r['cap_recall_at_k']:.3f} | {r['cap_lift']:.2f} |")

    lines = [
        "# Missed-visit risk model — evaluation report",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `python -m ml.train`. Model version `{MODEL_VERSION}`.",
        "",
        f"**Selected model: `{result['chosen']}`** (rule: keep logistic regression unless boosting beats it on validation AUC by > {SELECTION_MARGIN}).",
        "",
        "## Splits",
        "",
        f"Patients hashed into pools {POOL_SPLIT}; train = pool train & scheduled < {VALID_START:%Y-%m-%d}; "
        f"valid = pool valid & [{VALID_START:%Y-%m-%d}, {TEST_START:%Y-%m-%d}); test = pool test & ≥ {TEST_START:%Y-%m-%d}. "
        "No patient in two splits; no future information in training rows.",
        "",
        "| split | rows | missed rate |", "| --- | --- | --- |",
        *[f"| {k} | {len(v):,} | {v.missed.mean():.3f} |" for k, v in splits.items()],
        "",
        "## Metrics",
        "",
        f"Capacity metric: within each facility-week, rank appointments by score and select the top {CAPACITY_SHARE:.0%}. "
        "`precision@k` is the share of selected appointments that were actually missed; `lift` is precision@k ÷ base rate.",
        "",
        "| split | model | n | base rate | AUC | PR-AUC | Brier | ECE | precision@k | recall@k | lift |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *[row(s, mo) for s in ["valid", "test"] for mo in ["rules", "logistic", "boosting"]],
        "",
    ]
    if ceiling:
        lines += [
            "## Signal ceiling (synthetic data only)",
            "",
            "The generator's hidden per-patient propensity is available for synthetic cohorts. Scoring the test rows with that "
            "hidden truth gives the best AUC any model could reach, because each appointment still carries irreducible randomness.",
            "",
            "| oracle | AUC |", "| --- | --- |",
            f"| latent propensity only | {ceiling['theta_only_auc']:.3f} |",
            f"| latent propensity + known lead-time / distance / streak effects | {ceiling['theta_plus_known_effects_auc']:.3f} |",
            f"| **selected model (observable history only)** | **{m['test'][result['chosen']]['auc']:.3f}** |",
            "",
        ]
    lines += [
        "## Calibration on test (selected model)",
        "",
        calibration_table(te.missed.astype(int).values, p).round(3).to_markdown(index=False),
        "",
        "## Risk bands",
        "",
        f"Thresholds from training-score quantiles: medium ≥ {result['thresholds']['medium']:.3f} (50th pct), high ≥ {result['thresholds']['high']:.3f} (80th pct).",
        "",
        pd.DataFrame({"band": band(p, result["thresholds"]), "missed": te.missed.astype(int)})
        .groupby("band").missed.agg(n="size", observed_miss_rate="mean").round(3).reindex(["low", "medium", "high"]).to_markdown(),
        "",
        "## Cold start (test rows with no personal history)",
        "",
    ]
    pooled = result["cold_start"].pooled(te)
    cs = pd.DataFrame({"basis": pooled.basis, "missed": te.missed.astype(int), "p": p})
    lines += [cs.groupby("basis").agg(n=("missed", "size"), observed=("missed", "mean"), predicted=("p", "mean")).round(3).to_markdown(), ""]
    lines += ["## Fairness (test, selected model)", ""]
    for col in ["gender", "age_band", "region", "facility_id"]:
        lines += [f"### by {col}", "", fairness_table(te, p, col).to_markdown(index=False), ""]
    lines += [
        "## Notes",
        "",
        "- `region` is **not** a model feature; it appears only in this audit. The synthetic generator gives region no causal effect; any gap seen here is mediated by distance band.",
        "- Rows with basis `group` are scored from similar patients (facility × diabetes × drug count × age band) with partial pooling; the UI must label them as group estimates.",
        "- Reasons shown to users come from the logistic model's per-row contributions (`ml.train.explain_rows`).",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def log_mlflow(result: dict) -> None:
    try:
        import mlflow
    except Exception:
        return
    root = Path(__file__).resolve().parents[2]
    mlflow.set_tracking_uri(f"sqlite:///{root / 'mlflow.db'}")
    mlflow.set_experiment("missed_visit_risk")
    with mlflow.start_run(run_name=MODEL_VERSION):
        mlflow.log_params({"chosen": result["chosen"], "capacity_share": CAPACITY_SHARE, "cold_start_k": result["cold_start"].k,
                           "valid_start": str(VALID_START.date()), "test_start": str(TEST_START.date())})
        for split in ["valid", "test"]:
            for model, r in result["metrics"][split].items():
                for k in ["auc", "pr_auc", "cap_precision_at_k", "cap_recall_at_k"]:
                    mlflow.log_metric(f"{split}_{model}_{k}", r[k])
                if "brier" in r:
                    mlflow.log_metric(f"{split}_{model}_brier", r["brier"])
        mlflow.log_dict(result["thresholds"], "thresholds.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=None, help="generator output dir instead of the database")
    ap.add_argument("--as-of", default=str(pd.Timestamp.today().date()))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.csv:
        from ml.features import load_tables_from_csv
        tables = load_tables_from_csv(args.csv)
    else:
        from app.db import engine
        from ml.features import load_tables_from_db
        tables = load_tables_from_db(engine)

    ft = build_feature_table(tables, pd.Timestamp(args.as_of))
    splits = make_splits(ft, args.seed)
    result = fit_all(splits, args.seed)
    path = save_artifact(result)
    truth = (args.csv or Path(__file__).resolve().parents[2] / "data" / "synth" / "out") / "_truth_patients.csv"
    write_report(result, splits, truth_path=truth)
    log_mlflow(result)

    print(f"chosen: {result['chosen']}   artifact: {path}   report: {REPORT_PATH}")
    for split in ["valid", "test"]:
        for model in ["rules", "logistic", "boosting"]:
            r = result["metrics"][split][model]
            print(f"  {split:5s} {model:9s} n={r['n']:5d} auc={r['auc']:.3f} pr_auc={r['pr_auc']:.3f} "
                  f"p@k={r['cap_precision_at_k']:.3f} (base {r['base_rate']:.3f}, lift {r['cap_lift']:.2f})")
    print(json.dumps(result["thresholds"]))


if __name__ == "__main__":
    main()
