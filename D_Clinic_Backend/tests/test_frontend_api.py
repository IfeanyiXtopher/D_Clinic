"""Step 10 demo endpoints (skipped when the database is empty)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


def _db_ok() -> bool:
    try:
        from app.db import engine

        with engine.connect() as c:
            return c.execute(text("SELECT count(*) FROM facilities")).scalar() > 0
    except Exception:
        return False


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def test_eval_reports_need_no_database(client):
    r = client.get("/eval/reports")
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert {"worklist", "summary", "chatbot", "reckoner"} <= ids
    assert all("headline" in x and "body" not in x for x in r.json())
    one = client.get("/eval/reports/worklist")
    assert one.status_code == 200
    assert "extra returns" in one.json()["body"].lower()
    assert client.get("/eval/registry").status_code == 200
    assert client.get("/eval/reports/not-a-report").status_code == 404


@pytest.mark.skipif(not _db_ok(), reason="needs seeded database")
def test_facilities_and_demo_have_no_identity(client):
    fac = client.get("/facilities")
    assert fac.status_code == 200 and fac.json()
    blob = fac.text
    assert "full_name" not in blob and "phone" not in blob
    ctx = client.get("/demo/context")
    assert ctx.status_code == 200
    body = ctx.json()
    assert body["worklist_as_of"] == "2026-09-22"
    assert body["facilities"]
    assert body.get("chat_patient_id")
    assert "number" not in ctx.text


@pytest.mark.skipif(not _db_ok(), reason="needs seeded database")
def test_summary_feedback_is_enum_only(client):
    from app.db import engine

    with engine.connect() as c:
        pid = str(c.execute(text("SELECT id FROM patients LIMIT 1")).scalar())
    bad = client.post(f"/patients/{pid}/feedback", json={"verdict": "please call 08035551212"})
    assert bad.status_code == 422
    ok = client.post(f"/patients/{pid}/feedback", json={"verdict": "useful", "case_code": "C-TEST"})
    assert ok.status_code == 201
    with engine.connect() as c:
        ev = c.execute(
            text(
                """SELECT extra->>'verdict' FROM audit_events
                   WHERE action = 'summary.feedback' AND subject_id = :p
                   ORDER BY created_at DESC LIMIT 1"""
            ),
            {"p": pid},
        ).scalar()
    assert ev == "useful"
    got = client.get(f"/patients/{pid}/feedback")
    assert got.status_code == 200
    assert got.json()["verdict"] == "useful"
