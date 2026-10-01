"""Orchestrate de-id → scan → gateway → post-check → template fallback."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

from llm.check import CheckResult, check_summary
from llm.deid import DeidError, Packet, build_packet, new_case_code
from llm.gateway import PROMPT_VERSION, GatewayResult, complete
from llm.scan import scan_text
from llm.template import templated_summary

CASE_TTL_HOURS = 24


@dataclass
class SummaryResult:
    case_code: str
    facts: dict
    summary: str
    source: str  # model | template | refused
    check: str  # passed | failed_fallback | refused
    provider: str
    model: str | None
    prompt_version: str
    fallback_used: bool
    packet_hash: str
    extra_numbers: list[str]
    extra_drugs: list[str]
    missing_facts: list[str]
    refusal_reason: str | None = None
    latency_ms: int = 0

    def as_api(self, patient_id: str) -> dict:
        return {
            "patient_id": patient_id,
            "case_code": self.case_code,
            "facts": self.facts,
            "summary": self.summary,
            "source": self.source,
            "check": self.check,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "model_version": self.model or "template",
            "fallback_used": self.fallback_used,
            "packet_hash": self.packet_hash,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def summarize_packet(packet: Packet, *, complete_fn=complete) -> SummaryResult:
    inbound = scan_text(packet.canonical_json())
    if inbound:
        kinds = sorted({f.entity for f in inbound})
        raise DeidError(f"refused: packet contains {kinds}")

    payload = json.dumps(packet.to_prompt(), sort_keys=True)
    gw: GatewayResult = complete_fn(payload)
    template = templated_summary(packet)

    if gw.text:
        outbound = scan_text(gw.text)
        checked: CheckResult = check_summary(gw.text, packet)
        if not outbound and checked.ok:
            return SummaryResult(
                case_code=packet.case_code,
                facts=packet.to_facts(),
                summary=gw.text,
                source="model",
                check="passed",
                provider=gw.provider,
                model=gw.model,
                prompt_version=gw.prompt_version,
                fallback_used=False,
                packet_hash=packet.packet_hash(),
                extra_numbers=[],
                extra_drugs=[],
                missing_facts=checked.missing_facts,
                latency_ms=gw.latency_ms,
            )
        # Model leaked PII or invented a number/drug — ship the template instead.
        tmpl_check = check_summary(template, packet)
        return SummaryResult(
            case_code=packet.case_code,
            facts=packet.to_facts(),
            summary=template,
            source="template",
            check="failed_fallback",
            provider=gw.provider,
            model=gw.model,
            prompt_version=gw.prompt_version,
            fallback_used=True,
            packet_hash=packet.packet_hash(),
            extra_numbers=checked.extra_numbers,
            extra_drugs=checked.extra_drugs,
            missing_facts=tmpl_check.missing_facts,
            refusal_reason="outbound_pii" if outbound else "postcheck_failed",
            latency_ms=gw.latency_ms,
        )

    tmpl_check = check_summary(template, packet)
    return SummaryResult(
        case_code=packet.case_code,
        facts=packet.to_facts(),
        summary=template,
        source="template",
        check="passed" if tmpl_check.ok else "failed_fallback",
        provider=gw.provider,
        model=gw.model,
        prompt_version=gw.prompt_version or PROMPT_VERSION,
        fallback_used=gw.provider not in {"none", ""},
        packet_hash=packet.packet_hash(),
        extra_numbers=tmpl_check.extra_numbers,
        extra_drugs=tmpl_check.extra_drugs,
        missing_facts=tmpl_check.missing_facts,
        latency_ms=gw.latency_ms,
    )


def write_llm_request(engine: Engine, result: SummaryResult, *, patient_id: str | None,
                      deid_ok: bool, error: str | None = None) -> None:
    now = _now()
    row = {
        "id": str(uuid.uuid4()),
        "case_code": result.case_code,
        "patient_id": patient_id,
        "purpose": "summary",
        "provider": result.provider,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "packet_hash": result.packet_hash,
        "deid_ok": deid_ok,
        "postcheck_ok": result.check == "passed",
        "fallback_used": result.fallback_used,
        "source": result.source,
        "refusal_reason": result.refusal_reason,
        "latency_ms": result.latency_ms,
        "prompt_tokens": None,
        "completion_tokens": None,
        "error": error,
        "created_at": now,
        "expires_at": now + timedelta(hours=CASE_TTL_HOURS),
    }
    with engine.begin() as c:
        c.execute(
            text(
                """INSERT INTO llm_requests (
                       id, case_code, patient_id, purpose, provider, model, prompt_version, packet_hash,
                       deid_ok, postcheck_ok, fallback_used, source, refusal_reason, latency_ms,
                       prompt_tokens, completion_tokens, error, created_at, expires_at
                   ) VALUES (
                       :id, :case_code, :patient_id, :purpose, :provider, :model, :prompt_version, :packet_hash,
                       :deid_ok, :postcheck_ok, :fallback_used, :source, :refusal_reason, :latency_ms,
                       :prompt_tokens, :completion_tokens, :error, :created_at, :expires_at
                   )"""
            ),
            row,
        )


def summarize_patient(engine: Engine, patient_id: str, *, as_of: date | None = None,
                      persist: bool = True, complete_fn=complete) -> SummaryResult:
    from llm.load import fetch_clinical_record

    as_of = as_of or date.today()
    record = fetch_clinical_record(engine, patient_id, as_of)
    if record is None:
        raise KeyError(patient_id)
    try:
        packet = build_packet(record, as_of=as_of, case_code=new_case_code())
    except DeidError as exc:
        empty = SummaryResult(
            case_code=new_case_code(),
            facts={},
            summary="",
            source="refused",
            check="refused",
            provider="none",
            model=None,
            prompt_version=PROMPT_VERSION,
            fallback_used=False,
            packet_hash="",
            extra_numbers=[],
            extra_drugs=[],
            missing_facts=[],
            refusal_reason=str(exc),
        )
        if persist:
            write_llm_request(engine, empty, patient_id=patient_id, deid_ok=False, error=str(exc))
        raise
    result = summarize_packet(packet, complete_fn=complete_fn)
    if persist:
        write_llm_request(engine, result, patient_id=patient_id, deid_ok=True)
    return result
