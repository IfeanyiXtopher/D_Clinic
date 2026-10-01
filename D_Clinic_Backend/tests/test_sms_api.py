"""SMS simulator and Africa's Talking webhook against the seeded DB."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


def _db_ok() -> bool:
    try:
        from app.db import engine

        with engine.connect() as c:
            c.execute(text("SELECT 1 FROM dialogue_sessions LIMIT 0"))
            return c.execute(text("SELECT count(*) FROM patients")).scalar() > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ok(), reason="needs seeded database and dialogue_sessions migration")
AS_OF = "2026-09-26"


@pytest.fixture(scope="module")
def client():
    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def patient():
    from app.db import engine

    with engine.connect() as c:
        row = c.execute(
            text(
                """SELECT p.id::text, ph.number
                   FROM patients p
                   JOIN patient_phone_numbers ph ON ph.patient_id = p.id AND ph.active
                   JOIN appointments a ON a.patient_id = p.id AND a.status = 'scheduled'
                        AND a.scheduled_date >= :d
                   WHERE p.reminder_consent = 'granted'
                   LIMIT 1"""
            ),
            {"d": date(2026, 9, 26)},
        ).mappings().first()
    assert row, "need a consenting patient with a future visit"
    return dict(row)


def test_simulator_confirm_roundtrip(client, patient):
    r = client.post("/sms/outbound", json={"patient_id": patient["id"], "as_of": AS_OF})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "confirming"
    assert "2026-" not in r.json()["reply"]
    r2 = client.post("/sms/inbound", json={"patient_id": patient["id"], "body": "1", "as_of": AS_OF})
    assert r2.status_code == 200
    assert r2.json()["task_completed"] == "confirmed"
    assert r2.json()["patient_id"] == patient["id"]
    thread = client.get(f"/sms/threads/{patient['id']}")
    assert thread.status_code == 200
    assert thread.json()["messages"]
    assert thread.json()["messages"][0].get("at")
    assert "calls" in thread.json()
    assert "number" not in thread.text and "full_name" not in thread.text


def test_africastalking_webhook_unknown_number(client):
    r = client.post(
        "/sms/webhook",
        data={"from": "08030000000", "to": "40123", "text": "I go come", "date": AS_OF, "id": "AT1"},
    )
    assert r.status_code == 200
    assert "register" in r.json()["reply"].lower()


def test_medical_creates_staff_task(client, patient):
    r = client.post(
        "/sms/inbound",
        json={"patient_id": patient["id"], "body": "My head is paining me and my BP is high", "as_of": AS_OF,
              "session_id": f"med-{patient['id']}"},
    )
    assert r.status_code == 200
    assert r.json()["staff_task"] == "medical_callback"
    thread = client.get(f"/sms/threads/{patient['id']}")
    kinds = {t["kind"] for t in thread.json()["staff_tasks"]}
    assert "medical_callback" in kinds
