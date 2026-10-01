"""Ready-reckoner retrieval, next-step table, grounded refusal (no database)."""

from __future__ import annotations

from llm.deid import build_packet
from reckoner.ask import ask
from reckoner.chunk import load_chunks
from reckoner.index import build_index
from reckoner.next_step import next_step
from reckoner.retrieve import retrieve

from datetime import date


def test_chunks_have_hearts_and_national_ids():
    ids = {c.id for c in load_chunks()}
    assert "H-04" in ids and "H-08" in ids and "N-03" in ids
    assert all(c.body for c in load_chunks())


def test_retrieve_first_line_drug():
    index = build_index()
    hits = retrieve("What is the first protocol drug if not yet on treatment?", index=index)
    assert hits[0].chunk.id == "H-04"
    assert hits[0].method == "tfidf"
    assert "amlodipine 5 mg" in hits[0].chunk.body.lower()


def test_embed_skips_when_provider_is_tfidf(monkeypatch):
    from llm.gateway import embed

    monkeypatch.setattr("app.settings.settings.embedding_provider", "tfidf")
    res = embed(["amlodipine 5 mg once daily"])
    assert res.vectors is None and res.provider == "tfidf"


def test_dense_retrieve_uses_gateway_vectors(monkeypatch):
    import numpy as np
    from llm.gateway import EmbedResult

    index = build_index()
    n, dim = len(index["chunks"]), 8
    rng = np.random.default_rng(0)
    index = {**index, "dense": rng.normal(size=(n, dim)).astype(np.float32)}
    h04 = index["ids"].index("H-04")
    query = index["dense"][h04]

    monkeypatch.setattr(
        "llm.gateway.embed",
        lambda texts: EmbedResult([query.tolist()], "openai", "text-embedding-3-small", None),
    )
    hits = retrieve("first protocol drug", index=index)
    assert hits[0].method == "dense"
    assert hits[0].chunk.id == "H-04"


def test_ask_cites_and_keeps_doses():
    index = build_index()
    res = ask("What dose of amlodipine is step 1?", index=index)
    assert not res.refused
    assert "5" in res.answer
    assert any(c["id"] == "H-04" for c in res.citations)


def test_oos_malaria_is_refused():
    res = ask("What artemether dose for severe malaria?")
    assert res.refused
    assert "not covered" in res.answer.lower()


def test_invented_dose_would_fail_check():
    from reckoner.ask import dose_check
    from reckoner.retrieve import retrieve

    hits = retrieve("amlodipine step 1")
    assert not dose_check("Give amlodipine 25 mg tonight", hits)


def test_next_step_table():
    assert next_step(128, 78, [{"name": "Amlodipine", "dosage": "5 mg"}]).action == "continue"
    ns = next_step(156, 94, [{"name": "Amlodipine", "dosage": "5 mg"}])
    assert ns.action == "step_up" and "10 mg" in ns.guidance
    assert next_step(156, 94, []).action == "start_step_1"
    assert next_step(190, 80, []).action == "refer"


def test_summary_packet_uses_hearts_table():
    p = build_packet(
        {
            "age": 58,
            "gender": "female",
            "bp_history": [{"systolic": 156, "diastolic": 94, "recorded_at": date(2026, 9, 5)}],
            "drugs": [{"name": "Amlodipine", "dosage": "5 mg", "frequency": "OD"}],
            "attendance": {"visits_12m": 3, "missed_12m": 0, "last_visit_at": date(2026, 9, 5)},
            "program_status": "under_care",
        },
        as_of=date(2026, 9, 26),
    )
    assert "10 mg" in p.suggested_next_step
    assert "not a prescription" in p.suggested_next_step.lower() or "Clinician" in p.suggested_next_step
