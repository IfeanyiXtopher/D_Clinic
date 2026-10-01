"""Step 8 — gateway-only rule, de-id refusals, audit extra, responsible-AI doc."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from llm.deid import DeidError, build_packet
from llm.gateway import load_prompt
from llm.scan import scan_text
from tests.test_deid import AS_OF, _record
from tests.test_gateway_boundary import (
    test_only_gateway_contains_provider_urls,
    test_only_gateway_imports_an_llm_client,
)

REPO = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]


def test_gateway_only_rule_is_enforced():
    test_only_gateway_imports_an_llm_client()
    test_only_gateway_contains_provider_urls()


def test_name_in_any_field_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(program_status="Call Mr Adebayo today"), as_of=AS_OF)


def test_phone_in_any_field_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(program_status="callback 08035551212"), as_of=AS_OF)


def test_nin_in_any_field_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(drugs=[{"name": "Amlodipine 22345678901", "dosage": "5 mg"}]), as_of=AS_OF)


def test_nin_key_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(nin="22345678901"), as_of=AS_OF)


def test_exact_iso_date_in_any_field_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(program_status="overdue since 2026-01-15"), as_of=AS_OF)


def test_written_calendar_date_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(program_status="due January 15, 2026"), as_of=AS_OF)


def test_address_in_any_field_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(
            _record(drugs=[{"name": "Amlodipine 15 Adeola Odeku Street", "dosage": "5 mg"}]),
            as_of=AS_OF,
        )


def test_street_address_key_refuses():
    with pytest.raises(DeidError, match="refused"):
        build_packet(_record(street_address="15 Adeola Odeku Street"), as_of=AS_OF)


def test_scan_labels_address_nin_and_long_date():
    kinds = {f.entity for f in scan_text("NIN 22345678901 at 12 Allen Avenue on March 3, 2025")}
    assert "ADDRESS" in kinds
    assert "NG_NIN" in kinds
    assert "DATE_TIME" in kinds


def test_clean_packet_still_builds():
    p = build_packet(_record(), as_of=AS_OF)
    assert p.last_bp["when"] == "3 weeks ago"
    assert not scan_text(p.canonical_json())


def test_every_prompt_file_is_loadable():
    prompt_dir = BACKEND / "llm" / "prompts"
    names = sorted(p.stem for p in prompt_dir.glob("*.txt"))
    assert names == ["nlu_v1", "reckoner_v1", "rephrase_v1", "summary_v1"]
    for name in names:
        text = load_prompt(name)
        assert len(text) > 20
        assert "full_name" not in text
        assert "phone" not in text.lower() or "do not" in text.lower()


def test_responsible_ai_has_required_sections():
    text = (REPO / "docs" / "responsible_ai.md").read_text(encoding="utf-8")
    for heading in (
        "## Fairness",
        "## Privacy and data protection",
        "Nigeria Data Protection Act",
        "HIPAA Safe Harbor",
        "## Human in the loop",
        "## Opt-out",
        "## Known limitations",
    ):
        assert heading in text, heading
    assert "TBD" not in text
    assert "0.640" in text or "0.648" in text


def test_hitl_checklist_covers_each_feature():
    text = (REPO / "docs" / "hitl_checklist.md").read_text(encoding="utf-8")
    for feature in ("Risk score", "Worklist", "Summary", "Chatbot", "Ready-reckoner"):
        assert feature in text
    assert "[x]" in text


def test_audit_refuses_identity_in_extra():
    from app.audit import AuditError, FORBIDDEN_EXTRA

    assert "phone" in FORBIDDEN_EXTRA and "full_name" in FORBIDDEN_EXTRA
    from unittest.mock import MagicMock

    with pytest.raises(AuditError, match="refused"):
        from app.audit import write_event

        write_event(MagicMock(), action="summary.viewed", extra={"phone": "0803"})


def test_registry_lists_production_models():
    from ml.registry import load_registry, production_version

    data = load_registry()
    assert data["models"]
    assert production_version("missed_visit_risk") == "missed_visit_v1"
    assert production_version("worker_summary") == "template"


def test_metrics_render_includes_required_series():
    from app.metrics import inc, render_prometheus, snapshot

    inc("followup_pii_refusals_total", 0)
    text = render_prometheus()
    for name in (
        "followup_pii_refusals_total",
        "followup_check_failures_total",
        "followup_unsafe_intents_total",
        "followup_latency_p95_ms",
    ):
        assert name in text
    assert "followup_pii_refusals_total" in snapshot()
