"""POST /patients/{id}/summary against the seeded database (skipped if unreachable)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


def _db_ok() -> bool:
    try:
        from app.db import engine

        with engine.connect() as c:
            c.execute(text("SELECT 1 FROM llm_requests LIMIT 0"))
            return c.execute(text("SELECT count(*) FROM patients")).scalar() > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ok(), reason="needs seeded database and llm_requests migration")


@pytest.fixture(scope="module")
def client():
    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def patient_id():
    from app.db import engine

    with engine.connect() as c:
        return str(
            c.execute(
                text(
                    """SELECT p.id FROM patients p
                       JOIN blood_pressures b ON b.patient_id = p.id
                       WHERE p.deleted_at IS NULL
                       GROUP BY p.id HAVING count(*) >= 2 LIMIT 1"""
                )
            ).scalar()
        )


def test_summary_returns_facts_and_no_identity(client, patient_id):
    r = client.post(f"/patients/{patient_id}/summary", json={"as_of": "2026-09-26"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["patient_id"] == patient_id
    assert body["case_code"].startswith("C-")
    assert body["summary"]
    assert body["check"] in {"passed", "failed_fallback"}
    assert body["prompt_version"] == "summary_v1"
    facts = body["facts"]
    assert "last_bp" in facts or facts.get("program_status")
    blob = str(body)
    assert "full_name" not in blob
    assert "0803" not in blob
    assert "street_address" not in blob
    from llm.scan import scan_text

    assert not scan_text(body["summary"])


def test_summary_persists_audit_row(client, patient_id):
    from app.db import engine

    r = client.post(f"/patients/{patient_id}/summary", json={"as_of": "2026-09-26", "persist": True})
    assert r.status_code == 200
    code = r.json()["case_code"]
    with engine.connect() as c:
        row = c.execute(text("SELECT purpose, deid_ok, packet_hash FROM llm_requests WHERE case_code = :c"),
                        {"c": code}).mappings().first()
    assert row and row["purpose"] == "summary" and row["deid_ok"] is True and row["packet_hash"]
    with engine.connect() as c:
        ev = c.execute(
            text(
                """SELECT action, extra->>'case_code' AS code FROM audit_events
                   WHERE subject_id = :p AND action = 'summary.viewed'
                   ORDER BY created_at DESC LIMIT 1"""
            ),
            {"p": patient_id},
        ).mappings().first()
    assert ev and ev["action"] == "summary.viewed" and ev["code"] == code


def test_unknown_patient_404(client):
    r = client.post("/patients/00000000-0000-0000-0000-000000000000/summary")
    assert r.status_code == 404


def test_as_of_is_accepted(client, patient_id):
    r = client.post(f"/patients/{patient_id}/summary", json={"as_of": date(2026, 6, 1).isoformat(), "persist": False})
    assert r.status_code == 200
    assert r.json()["facts"]
