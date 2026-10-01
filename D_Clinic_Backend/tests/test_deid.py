"""De-identification, post-check and gateway boundary (Step 4)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from llm.check import check_summary, extra_drugs, extra_numbers
from llm.deid import FORBIDDEN_KEYS, DeidError, age_band, build_packet, relative_when
from llm.scan import scan_text
from llm.summary import summarize_packet
from llm.template import templated_summary

AS_OF = date(2026, 9, 26)


def _record(**over):
    rec = {
        "age": 58,
        "gender": "female",
        "hypertension": "yes",
        "diabetes": "no",
        "bp_history": [{"systolic": 156, "diastolic": 94, "recorded_at": AS_OF - timedelta(days=21)}],
        "drugs": [{"name": "Amlodipine", "dosage": "5 mg", "frequency": "OD"}],
        "attendance": {
            "visits_12m": 4,
            "missed_12m": 2,
            "last_visit_at": AS_OF - timedelta(days=21),
            "days_overdue": 14,
        },
        "last_call": {"result_type": "agreed_to_visit", "recorded_at": AS_OF - timedelta(days=3)},
        "risk": {"band": "high", "basis": "personal", "reasons": ["uncontrolled BP"]},
        "program_status": "overdue",
    }
    rec.update(over)
    return rec


def test_phone_in_note_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(notes="Please call 0803 555 1212 before the visit"), as_of=AS_OF)


def test_full_name_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(full_name="Ada Okafor"), as_of=AS_OF)


def test_phone_smuggled_in_drug_name_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(drugs=[{"name": "Amlodipine 08035551212", "dosage": "5 mg"}]), as_of=AS_OF)


def test_packet_has_relative_dates_not_calendar():
    p = build_packet(_record(), as_of=AS_OF)
    blob = p.canonical_json()
    assert "2026-" not in blob and "2025-" not in blob
    assert p.last_bp["when"] == "3 weeks ago"
    assert p.age_band == "55-64"
    assert p.sex == "female"
    assert "Amlodipine" in [d["name"] for d in p.drugs]
    assert p.case_code.startswith("C-")


def test_scan_finds_nigerian_phone_and_honorific():
    hits = {f.entity for f in scan_text("Call Mr Adebayo at 08031234567")}
    assert "PHONE_NUMBER" in hits
    assert "PERSON" in hits


def test_age_band_and_relative_when():
    assert age_band(17) == "0-17" and age_band(58) == "55-64" and age_band(80) == "75+"
    assert relative_when(AS_OF, AS_OF) == "today"
    assert relative_when(AS_OF - timedelta(days=1), AS_OF) == "yesterday"
    assert relative_when(AS_OF + timedelta(days=4), AS_OF) == "in 4 days"


def test_template_passes_postcheck_and_keeps_facts():
    p = build_packet(_record(), as_of=AS_OF)
    text = templated_summary(p)
    chk = check_summary(text, p)
    assert chk.ok
    assert "156/94" in text and "Amlodipine" in text and "high" in text


def test_invented_number_and_drug_fail_postcheck():
    p = build_packet(_record(), as_of=AS_OF)
    bad = templated_summary(p) + " Last BP was 200/130 on Losartan."
    assert "200" in extra_numbers(bad, p)
    assert "losartan" in extra_drugs(bad, p)
    assert not check_summary(bad, p).ok


def test_pipeline_falls_back_when_model_hallucinates():
    p = build_packet(_record(), as_of=AS_OF)
    from llm.gateway import GatewayResult, PROMPT_VERSION

    def fake(_payload):
        return GatewayResult(
            templated_summary(p) + " Last BP was 200/130 on Losartan. Call Mr Adebayo at 08031234567.",
            "mock", "sloppy", PROMPT_VERSION, 1, None, None, None,
        )

    res = summarize_packet(p, complete_fn=fake)
    assert res.fallback_used and res.source == "template" and res.check == "failed_fallback"
    assert "200/130" not in res.summary
    assert "Losartan" not in res.summary
    assert "Adebayo" not in res.summary
    assert check_summary(res.summary, p).ok


def test_forbidden_keys_cover_adr():
    for k in ("full_name", "phone", "street_address", "date_of_birth", "nin", "notes", "body"):
        assert k in FORBIDDEN_KEYS


def test_loader_sql_never_selects_identity_columns():
    src = (Path(__file__).resolve().parents[1] / "llm" / "load.py").read_text(encoding="utf-8")
    sql = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#") and ("SELECT" in line.upper() or "FROM" in line.upper())
    )
    for col in ("full_name", "date_of_birth", "street_address", "village_or_colony"):
        assert col not in sql
