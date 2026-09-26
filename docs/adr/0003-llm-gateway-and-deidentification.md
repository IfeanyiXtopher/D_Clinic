# ADR-0003: Single LLM gateway and de-identification boundary

**Status:** Accepted — 2026-09-26

## Context

Health status is sensitive personal data (Nigeria Data Protection Act 2023;
HIPAA in the US). The MVP may use a hosted model (OpenAI) as an optional
provider and will use a local model by default. In both cases patient identity
must never be present in a prompt, a reply, a log, or a training set.

## Decision

- Exactly **one module**, `D_Clinic_Backend/llm/gateway.py`, may import an LLM
  client. A test enforces this by scanning imports.
- Every prompt is built from a **packet** produced by `llm/deid.py` from
  structured fields only: age band, sex, relative dates ("3 weeks ago"),
  readings, drugs, attendance counts, call outcome, risk band and basis.
  No names, phone numbers, addresses, national IDs, exact dates, or free text.
- **Microsoft Presidio** scans the packet and the reply. Any detected PII
  entity aborts the request and writes an audit event.
- A **random case code per request** links the reply back to the patient. The
  map lives only in our database with a short TTL and is not derived from any
  patient attribute.
- A **post-check** verifies that every number and drug name in a generated
  summary exists in the packet; otherwise the templated fallback is used.
- `llm_requests` records model, prompt version, packet hash, pass/fail,
  latency, token counts. Packet bodies are not stored by default.
- Providers are interchangeable behind one interface: Ollama (default),
  OpenAI (optional). Switching is a configuration change.

## Consequences

- The "move to a private model" story is a config switch, not a refactor.
- Free-text clinical notes are out of scope until a tested redaction
  pipeline exists.
