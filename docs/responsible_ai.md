# Responsible AI — Followup-AI

Completed in Step 8 with measured results from the synthetic cohort.

## Purpose and intended use

Support health workers running a hypertension/diabetes follow-up program by
(1) estimating which scheduled visits are likely to be missed, (2) ordering the
daily call list, (3) summarizing a patient's structured record, (4) letting
patients confirm or move a visit by text, and (5) answering protocol questions
with citations.

This is a layer beside [Simple](https://docs.simple.org/), not a clinic EHR and
not a prescribing system.

## What the system never does

- Diagnose, change a prescription, or issue a clinical instruction.
- Send a message that was not generated from an approved template or reviewed
  by a human (SMS replies are templates; the model may only rephrase).
- Book, cancel, or move a visit outside slots the facility has opened.
- Place identity (name, phone, address, national ID, exact dates, free text)
  into a model prompt, reply, log, or training set.
- Use ethnicity, tribe, religion, nationality, or region as a predictive
  feature. These fields exist in the synthetic data only for fairness audits.
- Reduce or withhold care because of a risk score. A high score creates a
  support task; it never removes anyone from a list.

## Human in the loop

Verified against the live API in [`docs/hitl_checklist.md`](hitl_checklist.md).

| Feature | Human decision point | Automation stops at |
| --- | --- | --- |
| Risk score | Worker decides whether and how to contact | A `p_missed`, band, basis and reasons |
| Worklist | Worker can skip, reorder in the clinic, records the call | Ranked list + suggested action |
| Summary | Displayed under structured facts; worker reads both | Five-line briefing + post-check status |
| Chatbot | Medical intent → staff call task; books only open slots | Intent + template reply |
| Ready-reckoner | Worker applies the protocol; tool is not a prescription | Cited extract + next-step table |

## Fairness

Audit dimensions: sex, age band, facility, region (synthetic only; region is
**not** a feature). Metrics: calibration by group, selection rate at 30%
worklist capacity vs base miss rate, false-negative rate at capacity.

Source: `docs/eval_reports/missed_visit_model.md` and
`notebooks/03_fairness_and_calibration.ipynb` (test split, selected logistic).

Headline (test, selected model; report table n = 2,063, miss rate 0.277,
AUC **0.640**, lift **1.34** at 30% capacity):

| group | n | base miss rate | selection rate | FNR at capacity | ECE |
| --- | ---: | ---: | ---: | ---: | ---: |
| female | 1,208 | 0.272 | 0.261 | 0.634 | 0.023 |
| male | 855 | 0.284 | 0.396 | 0.498 | 0.032 |
| under 40 | 233 | 0.318 | 0.528 | 0.419 | 0.103 |
| 70+ | 159 | 0.296 | 0.377 | 0.574 | 0.054 |
| Lagos | 1,010 | 0.260 | 0.313 | 0.555 | 0.010 |
| Ogun | 904 | 0.289 | 0.316 | 0.586 | 0.037 |
| Oyo | 149 | 0.315 | 0.349 | 0.638 | 0.068 |

Findings:

- No frequently-missing group is under-selected relative to its miss rate.
  Under-40s miss most and are selected most. Women are selected near their
  base rate; men slightly above theirs, so their false-negative rate at
  capacity is lower, not higher.
- The smallest region (`Oyo`, n = 149) is over-selected. The generator gives
  region no causal effect. Over-selection only adds support, so it is logged
  as a monitoring item rather than corrected with a different threshold.
  Under-selection of a high-miss group would block promotion.
- Cold-start rows (basis `group`): predicted 0.301 vs observed 0.319. The UI
  must label these as group estimates.

Promotion gate: do not ship a new risk model if any frequently-missing group
(n ≥ 100) is under-selected vs its base rate by more than the bootstrap
interval allows in the fairness notebook.

## Privacy and data protection

This prototype uses **synthetic patients only**. A real program needs a DPIA,
lawful basis, consent records, and counsel review before any personal data
is processed.

### Nigeria Data Protection Act 2023

Mapped to how this codebase behaves:

| NDPA 2023 principle | How this system implements it |
| --- | --- |
| Lawful basis / consent | SMS `STOP` stores `reminder_consent=denied`. No message is sent after that. |
| Purpose limitation | Models are only for missed-visit support, summaries, scheduling, and protocol lookup. |
| Data minimisation | Prompts contain age band, relative dates, BP, drugs, attendance — never name, phone, address, NIN, or exact calendar dates. |
| Storage limitation | `llm_requests` rows expire (`expires_at`, 24 h). Packet bodies are not stored; only a hash. |
| Integrity and confidentiality | Single gateway (ADR-0003). Presidio/regex scan inbound and outbound. |
| Accountability | `audit_events` for summary views, worklist rebuild/skip, and call results. `llm_requests` for every model/template briefing. |

### HIPAA Safe Harbor (45 CFR 164.514(b)(2))

The de-id packet and `llm/scan.py` refuse the Safe Harbor identifiers that
can appear in this workflow:

| Identifier | Handling |
| --- | --- |
| Names | Honorific + proper name refused; `full_name` / `name` keys refused |
| Geographic subdivision smaller than a state | Street-style addresses refused; `street_address` / `village` keys refused. Distance *band* (near/mid/far) is kept — it is not an address |
| Dates (except year) | ISO, slash, and written calendar dates refused; packet uses relative time only. Age is stored as a band |
| Phone / fax | Nigerian and `+234` forms refused |
| Email | Refused |
| National ID / NIN | 11-digit NIN and `nin` / `national_id` keys refused |
| Medical record / account / licence / vehicle / device / URL / IP / biometric / photo / unique codes | Not collected. Random per-request `case_code` is not derived from the patient |

Free-text notes are refused as a class (`notes`, `body`) because they are the
usual place leftover identifiers hide.

Architecture: ADR-0003. One gateway (`llm/gateway.py`). No other module may
import an LLM client or contain provider URLs (`tests/test_privacy_boundary.py`).

## Known limitations and failure modes

- **Synthetic transfer.** Magnitudes will differ in any real program. Retrain
  and re-audit before use.
- **Cold start.** Group estimates are labelled `basis=group`. They are not
  personal predictions.
- **Hallucinated doses / BP.** Small models can invent numbers. The post-check
  drops the model text and ships the template. Eval: sloppy model fallback
  100%; template factuality 1.00; PII rate 0 (`docs/eval_reports/summary.md`).
- **SMS languages.** Pidgin / Hausa / Yoruba evaluated on a scripted set
  (intent 1.00, unsafe 0, PII 0). Real SMS will be noisier; low-confidence
  and medical turns hand off to a human.
- **Ready-reckoner.** Educational HEARTS / PHC adaptation, not a legal
  protocol. Recall@4 0.94; out-of-scope refusal 1.00; in-scope refusal 0.04.
- **Worklist side effect.** Cold-start patients are 5% of the risk list vs
  17% of longest-overdue-first. Protect slots for new patients if the program
  wants that.
- **Live host RAM.** A 1–2 GB VPS cannot run Ollama. Live uses
  `LLM_PROVIDER=openai` or templates. Fine-tunes (Step 7) do not change live.

## Opt-out and transparency

- `stop` over SMS disables messaging. Consent is a stored record.
- Every score shows `basis` (group / mixed / personal) and top reasons.
- Every summary shows `prompt_version`, `model_version`, and whether the
  factuality check passed.
- Staff actions land in `audit_events`. Model calls land in `llm_requests`
  (hash only, no packet body).
