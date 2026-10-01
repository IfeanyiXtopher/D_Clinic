"""Weekly score-distribution drift vs the previous week (Step 9.5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.settings import REPO_ROOT

REPORT = REPO_ROOT / "docs" / "eval_reports" / "drift.md"


def _band_counts(engine: Engine, start, end) -> dict[str, int]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                """SELECT band, count(*) FROM risk_scores
                   WHERE scored_at >= :a AND scored_at < :b
                   GROUP BY band"""
            ),
            {"a": start, "b": end},
        ).all()
    return {str(b): int(n) for b, n in rows}


def _mean_p(engine: Engine, start, end) -> float | None:
    with engine.connect() as c:
        v = c.execute(
            text(
                """SELECT avg(p_missed) FROM risk_scores
                   WHERE scored_at >= :a AND scored_at < :b"""
            ),
            {"a": start, "b": end},
        ).scalar()
    return None if v is None else float(v)


def compute_drift(engine: Engine, *, as_of: datetime | None = None) -> dict:
    as_of = as_of or datetime.now(timezone.utc).replace(tzinfo=None)
    this_start = as_of - timedelta(days=7)
    prev_start = as_of - timedelta(days=14)
    current = {
        "mean_p": _mean_p(engine, this_start, as_of),
        "bands": _band_counts(engine, this_start, as_of),
    }
    previous = {
        "mean_p": _mean_p(engine, prev_start, this_start),
        "bands": _band_counts(engine, prev_start, this_start),
    }
    delta = None
    if current["mean_p"] is not None and previous["mean_p"] is not None:
        delta = current["mean_p"] - previous["mean_p"]
    alert = bool(delta is not None and abs(delta) >= 0.05)
    return {
        "as_of": as_of.isoformat(timespec="seconds"),
        "current": current,
        "previous": previous,
        "delta_mean_p": delta,
        "alert": alert,
    }


def render(report: dict) -> str:
    cur, prev = report["current"], report["previous"]
    delta = report["delta_mean_p"]
    delta_s = "n/a" if delta is None else f"{delta:+.3f}"
    flag = "ALERT: mean p_missed moved by ≥ 0.05" if report["alert"] else "No mean-shift alert."
    return "\n".join([
        "# Weekly risk-score drift",
        "",
        f"Generated {report['as_of']} UTC by `worker.tasks.weekly_drift_report`.",
        "",
        flag,
        "",
        "| window | mean p_missed | low | medium | high |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| previous 7d | {prev['mean_p'] if prev['mean_p'] is not None else 'n/a'} "
        f"| {prev['bands'].get('low', 0)} | {prev['bands'].get('medium', 0)} | {prev['bands'].get('high', 0)} |",
        f"| last 7d | {cur['mean_p'] if cur['mean_p'] is not None else 'n/a'} "
        f"| {cur['bands'].get('low', 0)} | {cur['bands'].get('medium', 0)} | {cur['bands'].get('high', 0)} |",
        "",
        f"Δ mean p_missed: **{delta_s}**. A score only adds a support task; an alert is for operators, not a threshold change.",
        "",
    ])


def write_report(engine: Engine, path: Path | None = None) -> dict:
    report = compute_drift(engine)
    dest = path or REPORT
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(report), encoding="utf-8")
    return report
