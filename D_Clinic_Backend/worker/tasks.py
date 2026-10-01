from __future__ import annotations

import logging

from worker.celery_app import celery

log = logging.getLogger(__name__)


@celery.task(name="worker.tasks.score_upcoming_appointments", bind=True, max_retries=2, default_retry_delay=300)
def score_upcoming_appointments(self, horizon_days: int = 60, facility_id: str | None = None) -> dict:
    """Nightly risk scoring. Idempotent per night: rows are appended with `scored_at`, and
    `latest_risk_scores` always shows the newest, so a retry cannot corrupt earlier results."""
    from app.db import engine
    from ml.predict import score_upcoming, write_scores

    try:
        scores = score_upcoming(engine, horizon_days=horizon_days, facility_id=facility_id)
        n = write_scores(scores, engine)
    except Exception as exc:  # pragma: no cover - retried by Celery
        log.exception("scoring failed")
        raise self.retry(exc=exc)
    summary = {"scored": int(n)}
    if n:
        summary["bands"] = scores.band.value_counts().to_dict()
        summary["basis"] = scores.basis.value_counts().to_dict()
    log.info("scored %s upcoming appointments: %s", n, summary)
    return summary


@celery.task(name="worker.tasks.build_daily_worklists", bind=True, max_retries=2, default_retry_delay=300)
def build_daily_worklists(self, list_date: str | None = None, facility_id: str | None = None, rebuild: bool = False) -> dict:
    """06:00 worklist build for every facility (or one). Idempotent: a day that is already built is left
    alone unless ``rebuild`` is set, and items with a recorded call result are never deleted."""
    from datetime import date

    from app.db import engine
    from app.worklist_service import build_and_store

    d = date.fromisoformat(list_date) if list_date else date.today()
    try:
        counts = build_and_store(engine, d, facility_id, rebuild=rebuild)
    except Exception as exc:  # pragma: no cover - retried by Celery
        log.exception("worklist build failed")
        raise self.retry(exc=exc)
    log.info("worklists for %s: %s", d, counts)
    return {"list_date": d.isoformat(), "facilities": counts}


@celery.task(name="worker.tasks.weekly_drift_report", bind=True, max_retries=1, default_retry_delay=300)
def weekly_drift_report(self) -> dict:
    """Write docs/eval_reports/drift.md from the last two weeks of risk_scores."""
    from app.db import engine
    from ml.drift import write_report

    try:
        report = write_report(engine)
    except Exception as exc:  # pragma: no cover
        log.exception("drift report failed")
        raise self.retry(exc=exc)
    log.info("drift report alert=%s delta=%s", report["alert"], report["delta_mean_p"])
    return {"alert": report["alert"], "delta_mean_p": report["delta_mean_p"]}
