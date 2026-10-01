# Pitch — Followup-AI beside Simple

Followup-AI is an open-source layer for a hypertension / diabetes follow-up
program. It is shaped to sit beside [Simple](https://docs.simple.org/) (Resolve
to Save Lives). It is not an EHR and it does not prescribe.

This note maps each working surface to a program use case: **screen**,
**metric**, and **where the code lives**. All numbers are from the synthetic
cohort and the published eval reports.

---

## 1. Who is likely to miss the next visit?

**Use case.** A facility has more overdue patients than call slots. Rank who to
try first without hiding anyone.

| | |
| --- | --- |
| **Screen** | Worklist — `/` — overdue and pre-visit tabs |
| **Metric** | **+15% extra returns per 100 calls** vs longest-overdue-first (20.9 vs 18.2). Report: [`docs/eval_reports/worklist.md`](eval_reports/worklist.md) |
| **Code** | `D_Clinic_Backend/ml/predict.py`, `ml/worklist.py`, `app/worklist_service.py` |
| **Model** | `missed_visit_v1` — logistic; ethnicity and region are never features. Card: [`docs/model_cards/missed_visit_risk.md`](model_cards/missed_visit_risk.md) |

The worker records **Agreed to visit** or **Call later** (Simple vocabulary).
A score only creates a call. It never removes a patient from care.

New patients use **partial pooling** (group rate shrunk toward the personal
record). See [`docs/writeup-identity-free-summaries.md`](writeup-identity-free-summaries.md)
for the briefing boundary; cold start is `D_Clinic_Backend/ml/cold_start.py`.

---

## 2. What should the worker know before they call?

**Use case.** Open a case stub (no name, no phone). Read facts, then a short
briefing that cannot invent a BP or a drug.

| | |
| --- | --- |
| **Screen** | Patient briefing — `/patients/:id` |
| **Metric** | Invented number/drug is not shown. Staff rating (useful / missing fact / wrong number) is logged. Eval: [`docs/eval_reports/summary.md`](eval_reports/summary.md) |
| **Code** | `D_Clinic_Backend/llm/deid.py`, `llm/gateway.py`, `llm/check.py`, `llm/summary.py` |
| **Prompt** | `D_Clinic_Backend/llm/prompts/summary_v1.txt` |

The packet the model sees has a case code, age band, relative times, BP/BS
series, and protocol drugs. Identity never enters the prompt. Write-up:
[`docs/writeup-identity-free-summaries.md`](writeup-identity-free-summaries.md).

---

## 3. Can the patient confirm or move the visit by SMS?

**Use case.** Outbound reminder; inbound confirm / reschedule / STOP / symptom.
The model may read wording. **Code** picks the clinic day and writes
`appointments`.

| | |
| --- | --- |
| **Screen** | SMS thread — `/chat` (simulator; production is the patient’s phone + staff history) |
| **Metric** | Scripted set: task completion 100%, unsafe 0, PII 0. [`docs/eval_reports/chatbot.md`](eval_reports/chatbot.md) |
| **Code** | `D_Clinic_Backend/chatbot/dialogue.py`, `nlu.py`, `tools.py`, `app/main.py` (`/sms/*`) |
| **Card** | [`docs/model_cards/sms_intent.md`](model_cards/sms_intent.md) |

A symptom opens a **worker callback**. STOP sets `reminder_consent = denied`.
Saturday is not an open slot.

---

## 4. What does the protocol say, with a citation?

**Use case.** On-shift lookup of WHO HEARTS / PHC text. Not a free chatbot.

| | |
| --- | --- |
| **Screen** | Protocol next step + Protocol Q&A on the patient page |
| **Metric** | Recall@4 94%, dose/number check 100%, out-of-scope refuse 100%. [`docs/eval_reports/reckoner.md`](eval_reports/reckoner.md) |
| **Code** | `D_Clinic_Backend/reckoner/retrieve.py`, `ask.py`, `next_step.py` |
| **Corpus** | `data/protocols/hearts.md`, `data/protocols/national_htn.md` |

The worker applies the protocol. The tool quotes and cites. An invented dose is
dropped.

---

## How this integrates with Simple

Followup-AI **reads Simple-shaped tables** and **writes Simple-shaped events**.
It does not replace Simple’s Android client or facility login.

| Simple concept | In this repo |
| --- | --- |
| Patients, phones, BP, drugs, appointments | `D_Clinic_Backend/app/models.py` (same names) |
| Visit = a recorded BP | [`docs/definitions.md`](definitions.md) |
| Call result `agreed_to_visit` / `remind_to_call_later` / `removed_from_overdue_list` | `POST /call-results` |
| Overdue / under care / LTFU | SQL views in Alembic `0002` |
| SMS communications | `communications` + `/sms/webhook` (Africa’s Talking shape) |

**Path to a real program**

1. Point the read models at a Simple replica (or a nightly export), not at the
   synthetic generator.
2. Keep identity on the Simple side. This layer only ever sees a de-identified
   packet or a redacted SMS line.
3. Worklist and call results can post back as Simple-compatible events, or
   Simple can own the write and this layer only ranks.

ADR: [`docs/adr/0001-stack.md`](adr/0001-stack.md).

---

## What a reviewer should click

1. Worklist (list date **2026-09-22** on the seeded cohort).
2. A case → briefing + protocol Q&A.
3. SMS → Send reminder → confirm or move a day.
4. Evaluation → operating process and measured results.

Responsible AI and HITL: [`docs/responsible_ai.md`](responsible_ai.md),
[`docs/hitl_checklist.md`](hitl_checklist.md).

Recorded walkthrough shot list: [`docs/walkthrough.md`](walkthrough.md).
