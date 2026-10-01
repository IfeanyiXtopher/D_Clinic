"""Ready-reckoner HTTP endpoints (needs app import; no DB required)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_ask_and_next_step_endpoints():
    from app.main import app

    client = TestClient(app)
    r = client.post("/reckoner/ask", json={"question": "What is the clinic blood pressure target?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] is False
    assert "140" in body["answer"]
    assert body["citations"]
    assert "full_name" not in r.text

    oos = client.post("/reckoner/ask", json={"question": "What artemether dose for severe malaria?"})
    assert oos.json()["refused"] is True

    ns = client.post("/reckoner/next-step", json={
        "systolic": 156, "diastolic": 94,
        "drugs": [{"name": "Amlodipine", "dosage": "5 mg"}],
    })
    assert ns.status_code == 200
    assert ns.json()["action"] == "step_up"
    assert ns.json()["cite"] == "H-05"
