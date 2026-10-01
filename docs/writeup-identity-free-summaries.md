# Technical write-up — Identity-free worker briefings

A health-worker briefing is useful only if it cannot leak a name or phone and
cannot invent a blood pressure. Followup-AI treats those as **code
invariants**, not as prompt etiquette.

This is the path a packet takes before any model sees it, and what happens
after the model writes.

## 1. The packet is the only object the model may see

`D_Clinic_Backend/llm/deid.py` builds a **de-identified packet** from the
structured record:

- `case_code` (not `patient_id`)
- age band and sex, not date of birth
- relative times (“12 days ago”), not calendar dates
- BP / blood-sugar series and protocol drugs
- attendance counts and program status

Forbidden keys (`full_name`, `phone`, `nin`, `street_address`, `notes`, …)
never appear on the object. If a scan finds identity-shaped text, packet
construction **refuses**. ADR: [`docs/adr/0003-llm-gateway-and-deidentification.md`](adr/0003-llm-gateway-and-deidentification.md).

The worker UI shows the same stub: **Case AB12CD34**, never a name.

## 2. One gateway

`D_Clinic_Backend/llm/gateway.py` is the only module that talks to a hosted or
local chat API. Prompts are files (`llm/prompts/summary_v1.txt`, `nlu_v1.txt`,
`reckoner_v1.txt`, `rephrase_v1.txt`). Switching provider does not change the
packet or the post-check.

The gateway **never raises** into the request path. No text means the caller
uses the deterministic briefing.

## 3. The check decides what the worker sees

`D_Clinic_Backend/llm/check.py` requires every number and protocol drug in the
draft to exist in the packet. Fail → the worker sees the structured fallback,
not the invented line. The footer records `check` and whether a fallback ran.

That is the operational rule: **a briefing that fails the check is not shown
as a model briefing.**

## 4. Staff rating is audit, not training

`POST /patients/{id}/feedback` accepts only `useful` | `missing_fact` |
`wrong_number`. No free text (identity risk). Rows go to `audit_events`. They
do not retrain the model and they do not edit the chart.

## 5. What this is not

- Not a chart copy. Facts stay visible above the five lines.
- Not a diagnosis. The prompt forbids it; the check does not need to “understand”
  clinical intent to reject a rogue dose.
- Not a claim about a live national program. Packets in
  `make eval-summary` are built from the synthetic HEARTS ladder. Promotion to
  a real Simple replica still needs the same check on de-identified program
  packets.

## Related

- Cold-start scores (partial pooling, no ethnicity/region in the group key):
  `D_Clinic_Backend/ml/cold_start.py`
- HITL stops: [`docs/hitl_checklist.md`](hitl_checklist.md)
- Scan extras (address, long date): `D_Clinic_Backend/llm/scan.py`
