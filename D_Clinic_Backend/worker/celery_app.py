"""Celery application and beat schedule.

Run a worker:   celery -A worker.celery_app worker -l info
Run the beat:   celery -A worker.celery_app beat -l info      (exactly one instance)

Requires Redis (``make up``). Tests run tasks eagerly without a broker.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.settings import settings

celery = Celery("followup_ai", broker=settings.redis_url, backend=settings.redis_url, include=["worker.tasks"])
celery.conf.update(
    timezone="Africa/Lagos",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        # Nightly: score every scheduled appointment due in the next 60 days.
        "score-upcoming-appointments": {
            "task": "worker.tasks.score_upcoming_appointments",
            "schedule": crontab(hour=2, minute=0),
            "kwargs": {"horizon_days": 60},
        },
        # 06:00 local: build every facility's worklist for the day, before the clinic opens.
        "build-daily-worklists": {
            "task": "worker.tasks.build_daily_worklists",
            "schedule": crontab(hour=6, minute=0),
        },
    },
)
