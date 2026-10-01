"""Step 9 — metrics, registry, drift, offline bundle."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

REPO = Path(__file__).resolve().parents[2]


def _db_ok() -> bool:
    try:
        from app.db import engine

        with engine.connect() as c:
            c.execute(text("SELECT 1 FROM risk_scores LIMIT 0"))
        return True
    except Exception:
        return False


def test_metrics_endpoint_is_prometheus():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.metrics import inc

    inc("followup_pii_refusals_total")
    r = TestClient(app).get("/metrics")
    assert r.status_code == 200
    assert "followup_pii_refusals_total" in r.text
    assert "followup_latency_p95_ms" in r.text
    assert r.headers["content-type"].startswith("text/plain")


def test_bundle_writes_manifest(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("offline_bundle", REPO / "scripts" / "bundle.py")
    bundle = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bundle)

    monkeypatch.setattr(bundle, "DEST", tmp_path / "offline-bundle")
    monkeypatch.setattr(bundle, "ROOT", REPO)
    assert bundle.main() == 0
    dest = tmp_path / "offline-bundle"
    assert (dest / "MANIFEST.txt").exists()
    text = (dest / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "No download" in text
    assert (dest / "registry.json").exists()
    assert (dest / "docs" / "mlops.md").exists()


def test_drift_render_without_rows():
    from ml.drift import render

    md = render({
        "as_of": "2026-09-27T00:00:00",
        "current": {"mean_p": None, "bands": {}},
        "previous": {"mean_p": None, "bands": {}},
        "delta_mean_p": None,
        "alert": False,
    })
    assert "Weekly risk-score drift" in md
    assert "n/a" in md


@pytest.mark.skipif(not _db_ok(), reason="needs migrated database")
def test_weekly_drift_task_eager():
    from app.db import engine
    from ml.drift import write_report
    from worker.celery_app import celery
    from worker.tasks import weekly_drift_report

    write_report(engine)
    celery.conf.task_always_eager = True
    out = weekly_drift_report.apply().get()
    assert "alert" in out
    assert (REPO / "docs" / "eval_reports" / "drift.md").exists()


@pytest.mark.skipif(not _db_ok(), reason="needs migrated database")
def test_health_unchanged():
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/health").json() == {"status": "ok"}
