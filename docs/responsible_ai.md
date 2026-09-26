# Responsible AI — Followup-AI

Living document. Sections marked *TBD* are completed in Step 8 with measured
results.

## Purpose and intended use

Support health workers running a hypertension/diabetes follow-up program by
(1) estimating which scheduled visits are likely to be missed, (2) ordering the
daily call list, (3) summarizing a patient's structured record, (4) letting
patients confirm or move a visit by text, and (5) answering protocol questions
with citations.

## What the system never does

- Diagnose, change a prescription, or issue a clinical instruction.
- Send a message that was not generated from an approved template or reviewed
  by a human.
- Book, cancel, or move a visit outside slots the facility has opened.
- Place identity (name, phone, address, national ID, exact dates, free text)
  into a model prompt, reply, log, or training set.
- Use ethnicity, tribe, religion, nationality, or region as a predictive
  feature. These fields exist in the synthetic data only for fairness audits.
- Reduce or withhold care because of a risk score. A high score creates a
  support task; it never removes anyone from a list.

## Human in the loop

| Feature | Human decision point |
| --- | --- |
| Risk score | Creates a task; the worker decides whether and how to contact |
| Worklist | Worker can reorder, skip, and records the outcome |
| Summary | Displayed under the raw structured facts; worker reads both |
| Chatbot | Books only open slots; medical intent → staff call task |
| Ready-reckoner | Quotes the protocol; worker applies it |

## Fairness

Audit dimensions: sex, age band, facility, region (synthetic). Metrics:
calibration by group, selection rate at worklist capacity vs. base rate, false
negative rate by group. Results: *TBD (Step 2.8, Step 8.4)*.

## Privacy and data protection

- De-identification checklist follows the HIPAA Safe Harbor identifiers and
  the Nigeria Data Protection Act 2023 principles of purpose limitation and
  data minimization.
- Architecture: see ADR-0003. Single gateway, Presidio scan both ways, random
  per-request case code, audit table.
- Synthetic data only in this repository. Real program data requires a DPIA,
  consent records, and counsel review before use.

## Known limitations and failure modes

- Cold-start scores are group estimates and are labelled as such.
- Small local models can omit facts; the post-check falls back to a template
  rather than ship an unverified sentence.
- SMS understanding in Pidgin, Hausa, and Yoruba is evaluated on a small set;
  low-confidence turns hand off to a human.
- Results on synthetic data do not transfer directly to any real program.

## Opt-out and transparency

- `stop` over SMS disables messaging. Consent is a stored, versioned record.
- Every score shows its basis (group / mixed / personal) and top reasons.
- Every summary shows the model version and whether the factuality check
  passed.
