# Followup-AI — Build Plan and Progress Tracker

AI follow-up layer for a hypertension / diabetes program, shaped to sit beside
[Simple](https://docs.simple.org/) (Resolve to Save Lives). Open source, MIT,
runs offline on synthetic patients, identity never enters a model.

This file is the single source of truth for **where the build is**. It is
updated at every milestone. Read the *Current position* line first, then the
step it points at.

## How to read this file

Status marks:

- `[ ]` not started
- `[~]` in progress
- `[x]` done and verified
- `[!]` blocked (reason given inline)

Every step lists: **Goal**, numbered **Tasks**, the **Artifact** it produces,
and a **Verify** command or check that proves it is done. Nothing is marked
`[x]` unless *Verify* passes.

## Current position

> **Step 2 — Missed-visit risk model: `[x]` done. Next: Step 3 (optimized worklist).**

## Prerequisites on the developer machine

| Tool | Needed from | Installed |
| --- | --- | --- |
| Python 3.11+ | Step 1 | yes (3.12.0) |
| Docker + Compose | Step 1 | yes (29.4) |
| Node 20+ | Step 10 | yes (24.15) |
| Ollama | Step 4 | **no** — install from https://ollama.com before Step 4 |
| pgvector extension | Step 6 | **no** on the local PostgreSQL 18 — either `brew install pgvector` or run `make up PROFILE=db` for Step 6 |
| Kaggle account | Step 7 | for free T4/P100 fine-tuning |
| OpenAI API key (optional) | Step 4, 7 | teacher model and comparison baseline only |

Folder names: the backend lives in `D_Clinic_Backend/`, the frontend in
`D_Clinic_Frontend/` (pre-existing folders, kept as-is).

Database: the developer's own PostgreSQL (`d_clinic`, credentials in the
gitignored `.env`; template in `.env.example`). Redis runs in Docker.

---

## Step 0 — Scope and repository foundation `[x]`

**Goal.** Decide what is being built, for whom, and the rules that every later
step obeys. Produce the skeleton so each step has a home.

1. `[x]` 0.1 Initialize git repository, `.gitignore`, MIT `LICENSE`.
2. `[x]` 0.2 Create repository skeleton (`docs/`, `data/`, `notebooks/`, `eval/`, backend, frontend).
3. `[x]` 0.3 Write this tracker.
4. `[x]` 0.4 ADR-0001: stack (FastAPI, Postgres, Celery, Ollama, React).
5. `[x]` 0.5 ADR-0002: chatbot built as "LLM understands, code decides"; no Rasa.
6. `[x]` 0.6 ADR-0003: single LLM gateway and de-identification boundary.
7. `[x]` 0.7 `docs/responsible_ai.md` baseline: purpose, limits, what the system never does.
8. `[x]` 0.8 README with the one-paragraph product description.

**Artifact.** Repository skeleton, `docs/BUILD_PLAN.md`, `docs/adr/000{1,2,3}-*.md`, `docs/responsible_ai.md`, `README.md`.

**Verify.** `git log --oneline | head -1` shows the Step 0 commit; `tree -L 2` matches the layout in README.

---

## Step 1 — Data foundation and synthetic cohort `[x]`

**Goal.** A Postgres schema that mirrors Simple's tables and a synthetic
generator producing a realistic 24-month program history, plus an EDA notebook.

1. `[x]` 1.1 `docker-compose.yml` (`redis`; optional `postgres` pgvector image under profile `db`); `Makefile` with `up`, `down`, `migrate`, `synth`, `seed`, `test`, `eda`.
2. `[x]` 1.2 Backend Python project (`D_Clinic_Backend/pyproject.toml`), `pydantic-settings` reading `.env`, Alembic migrations `0001` (tables) and `0002` (views).
3. `[x]` 1.3 SQLAlchemy models named after Simple in `app/models.py`: `facilities`, `users`, `patients`, `patient_phone_numbers`, `addresses` (`zone` = distance band, `state` = region for audits only), `medical_histories`, `blood_pressures`, `blood_sugars`, `prescription_drugs`, `appointments`, `call_results`, `communications`.
4. `[x]` 1.4 Generator `data/synth/generate.py`: 5 facilities, 6,000 patients in ~4 s, latent adherence propensity, HEARTS ladder (amlodipine → telmisartan → chlorthalidone), visits/misses/overdue/LTFU, call results with Simple's exact values and 15-day return behaviour, reminder SMS and multilingual replies (en / pcm / ha / yo) with truth intents, region correlated with distance but with **no causal effect**. Deterministic per seed.
5. `[x]` 1.5 `make seed` = migrate + generate + `COPY` load (idempotent, truncates first). 150-patient sample committed at `data/synth/sample/`; full output in gitignored `data/synth/out/`.
6. `[x]` 1.6 Views: `latest_blood_pressures`, `bp_controlled_latest`, `latest_appointments`, `patients_under_care`, `lost_to_follow_up`, `overdue_patients` (with `has_phone`, last call result, days overdue). Definitions in `docs/definitions.md`.
7. `[x]` 1.7 `notebooks/01_eda.ipynb` (built by `notebooks/build_01_eda.py`, executed): cohort, registrations, missed-visit label by facility / lead time / distance, region gap explained by distance, overdue & LTFU, BP control trend, call → return within 15 days, SMS reply intents and languages.
8. `[x]` 1.8 `tests/test_synth.py`: 11 invariants (determinism, no visit before registration, none after death or program end, monotone appointments, valid status/call values, one active ladder, missed rate 20–35%, `stop` revokes consent, no identity in truth files).

**Artifact.** Database `d_clinic` with 6,000 synthetic patients, 39k visits, 39k appointments, 5.6k call results, 47k communications; `docs/definitions.md`; executed EDA notebook.

**Verify.** `make seed && make test` → 11 passed; seed output reports overdue among under-care 48% (accepted range 30–50%, see `docs/definitions.md`), BP controlled 41%, missed-visit rate 29%.

**Measured on 2026-09-26.** Missed rate 29.1%; overdue/under-care 48.3%; LTFU 900; controlled 41.2%; call results 51/30/19; return within 15 days of a call: 63% after `agreed_to_visit`, 22% after `remind_to_call_later`, 1.5% after removal; SMS reply rate 29%.

---

## Step 2 — Predictive model: missed follow-up risk `[x]`

**Goal.** A calibrated, explainable model predicting that a scheduled visit
will be missed, with a cold-start path for new patients and a fairness audit.

1. `[x]` 2.1 Label: `missed = 1` if no BP recorded in `[scheduled − 3 d, scheduled + 7 d]`; cancelled appointments excluded; only closed windows labelled.
2. `[x]` 2.2 `ml/features.py`: 27 features computed strictly as of booking time (history, streaks, latest BP and change, ladder step, prior calls, time-aware facility rate, lead time, season, distance band). `tests/test_features.py` injects future BPs/calls/prescriptions and asserts features are unchanged — this test **caught a real leak** (facility-rate fill used a dataset-wide mean) which was fixed with a fixed prior.
3. `[x]` 2.3 Split: patients hashed into pools 60/15/25 **and** time-cut (train < 2026-03-01, valid Mar–May 2026, test ≥ 2026-06-01). Train 13,422 / valid 977 / test 2,028 rows.
4. `[x]` 2.4 Rule score, logistic regression, histogram gradient boosting. Selection rule: logistic unless boosting wins validation AUC by > 0.01 → **logistic selected**.
5. `[x]` 2.5 Metrics: AUC, PR-AUC, Brier, log-loss, ECE, calibration table, **precision/recall at worklist capacity** (top 30% within each facility-week — changed from a fixed top-20, which selected nearly everything in the smaller test pool).
6. `[x]` 2.6 MLflow tracking to `mlflow.db` (experiment `missed_visit_risk`), optional import so training never depends on it.
7. `[x]` 2.7 `ml/cold_start.py`: partial pooling `k = 3`; groups facility × diabetes × drug count × age band with back-off (min 30); outputs `basis`, `group_size`, `group_level`; pooled rate is also a model feature. Test asserts no protected attribute in groups.
8. `[x]` 2.8 `notebooks/02_missed_visit_model.ipynb` (ROC/PR, ceiling, precision-vs-list-size, calibration, coefficients, cold start, example reasons) and `notebooks/03_fairness_and_calibration.ipynb` (tables by sex/age/distance/region/facility, selection vs base rate, in-group calibration, region gap decomposed by distance, bootstrap interval for the smallest group, promotion gate).
9. `[x]` 2.9 `docs/model_cards/missed_visit_risk.md`.
10. `[x]` 2.10 `POST /risk/score`, `GET /risk/appointments/{id}`, `GET /risk/patients/{id}` in `app/main.py`; `risk_scores` table + `latest_risk_scores` view (migration 0003); Celery task `score_upcoming_appointments` on a 02:00 beat schedule (`worker/`). Reasons come only from positive-coefficient, actionable features (fixed a bug where good history rendered as "history of missed visits").

**Artifact.** `ml/artifacts/missed_visit_v1.joblib`; `docs/eval_reports/missed_visit_model.md`; model card; notebooks 02 & 03; API + worker; 2,373 upcoming appointments scored in `risk_scores`.

**Verify.** `make train` → test AUC 0.648, precision@30% 0.438 vs base 0.295 (lift 1.49); `make test` → 31 passed (generator, features/leakage, cold start, API, eager Celery task); report contains the signal-ceiling and subgroup tables.

**Measured on 2026-09-26 (test, n = 2,028).** rules AUC 0.626 / lift 1.43; **logistic 0.648 / 1.49**; boosting 0.649 / 1.47. Oracle ceiling from hidden propensity: 0.681 (0.704 with known effects). ECE 0.02. Cold-start `group` rows: predicted 0.289 vs observed 0.280. Fairness: no under-selection of any frequently-missing group; smallest region over-selected by 0.107 [0.028, 0.192] — logged as a monitoring item (see notebook 03 for reasoning).

**Open item.** Docker Desktop was not running, so the live Redis broker was not exercised; the Celery task is tested in eager mode. Start Docker and run `make up && make worker && make beat` to run the nightly schedule for real.

---

## Step 3 — Optimized worklist for frontline workers `[ ]`

**Goal.** A ranked, capacity-limited, explainable daily list that beats
"sort by days overdue" on returns-within-15-days per call.

1. `[ ]` 3.1 Worklist rules: skip `agreed_to_visit` < 15 days; resurface `remind_to_call_later`; drop died/moved/refused; protect slots for uncontrolled BP; capacity default 20.
2. `[ ]` 3.2 `GET /worklist?facility=&date=` with reasons, basis badge, suggested action.
3. `[ ]` 3.3 `POST /call-results` using Simple's exact `result_type` and `remove_reason` values.
4. `[ ]` 3.4 Celery Beat builds lists at 06:00 facility time; on-demand rebuild.
5. `[ ]` 3.5 Replay evaluation on synthetic history: risk-ranked vs days-overdue on return-within-15-days per call → `docs/eval_reports/worklist.md`.

**Artifact.** Worklist API and evaluation report.

**Verify.** `make eval-worklist` writes the report; `pytest tests/test_worklist.py` green.

---

## Step 4 — Patient summary for the health worker `[ ]`

**Goal.** Five-line summary from structured data, generated by a local model,
with identity stripped and every number checked against the source.

1. `[ ]` 4.1 `llm/deid.py` packet builder (age band, sex, relative dates, BP/BS history, drugs, attendance, call outcome, risk band + basis). Refuses on any PII.
2. `[ ]` 4.2 Presidio scan inbound and outbound.
3. `[ ]` 4.3 `llm/gateway.py`: one provider interface, Ollama default, OpenAI optional; versioned prompt files; `llm_requests` audit table.
4. `[ ]` 4.4 Post-check: every number and drug name in output must exist in packet; else fall back to templated summary and log.
5. `[ ]` 4.5 `POST /patients/{id}/summary` returning structured facts + summary + check status.
6. `[ ]` 4.6 Evaluation: 200 packets with `must_keep_facts.json`; factuality, omission, length, PDSQI-9-style rubric → `docs/eval_reports/summary.md`; `notebooks/04_summary_eval.ipynb`.
7. `[ ]` 4.7 Static test: no module outside `llm/gateway.py` imports an LLM client.

**Artifact.** Summary endpoint, evaluation report, prompt v1.

**Verify.** `pytest tests/test_deid.py` includes a fixture with a phone number in a note and asserts refusal; `make eval-summary` writes the report.

---

## Step 5 — Scheduling chatbot over SMS-style text `[ ]`

**Goal.** Confirm, reschedule, or cancel a visit through short text messages.
The LLM classifies; the state machine and tools decide.

1. `[ ]` 5.1 Dialogue state machine: `idle`, `confirming`, `choosing_slot`, `rescheduling`, `cancelling`, `handoff`.
2. `[ ]` 5.2 Structured-output NLU via Ollama JSON schema: `{intent, date_hint, time_hint, confirm, language, needs_human}`.
3. `[ ]` 5.3 Tools in code: `get_available_slots`, `book`, `reschedule`, `cancel`, `record_reply`.
4. `[ ]` 5.4 Templated replies; model may only rephrase; dates inserted by code after rephrase; Presidio scan.
5. `[ ]` 5.5 Safety: medical/symptom intent → fixed reply + staff call task; `stop` → consent off.
6. `[ ]` 5.6 Channels: in-app SMS simulator; generic SMS-provider webhook (Africa's Talking sandbox shape); fake provider in dev.
7. `[ ]` 5.7 Small intent classifier (DistilBERT or Qwen 0.6B) on synthetic SMS replies; compare with LLM on accuracy and CPU latency.
8. `[ ]` 5.8 Evaluation: 150 scripted dialogues incl. Pidgin/Hausa/Yoruba lines and adversarial prompts; intent/slot accuracy, task completion, unsafe-response rate = 0, PII-leak rate = 0 → `docs/eval_reports/chatbot.md`.

**Artifact.** Chatbot service, webhook, simulator, evaluation report, `docs/model_cards/sms_intent.md`.

**Verify.** `promptfoo eval -c eval/promptfoo/chatbot.yaml` passes thresholds; `pytest tests/test_dialogue.py` green.

---

## Step 6 — Ready-reckoner and on-the-job guidance `[ ]`

**Goal.** Protocol answers with citations from WHO HEARTS and a national
hypertension protocol, plus a deterministic "next step" lookup.

1. `[ ]` 6.1 Corpus in `data/protocols/` as text; chunk by protocol step.
2. `[ ]` 6.2 Local embeddings (`nomic-embed-text` or `bge-small`) into `pgvector`.
3. `[ ]` 6.3 Retrieval top-4, strict grounded prompt, "not covered" refusal, dose post-check.
4. `[ ]` 6.4 Structured mode: BP band × current drug → next step table, used by Step 4 `suggested_next_step`.
5. `[ ]` 6.5 Evaluation: 60–100 gold Q&A + 20 out-of-scope; recall@4, faithfulness, refusal accuracy → `docs/eval_reports/reckoner.md`.

**Artifact.** `POST /reckoner/ask`, next-step table, evaluation report.

**Verify.** `make eval-reckoner` writes the report with recall@4 and faithfulness.

---

## Step 7 — Fine-tune a local model `[ ]`

**Goal.** A QLoRA-adapted small open model for summaries and SMS rephrasing,
exported to GGUF, served by Ollama, evaluated against the base model.

1. `[ ]` 7.1 Build 3,000–5,000 de-identified packets; generate targets with a teacher (larger open model or OpenAI); filter with Step 4 checks; hold out 10% by patient.
2. `[ ]` 7.2 `notebooks/05_finetune_qlora.ipynb` (Kaggle T4/P100): Qwen3 4B or Llama 3.2 3B, rank 16, 1–2 epochs, MLflow logging.
3. `[ ]` 7.3 Merge → GGUF → `Q4_K_M` → `Modelfile` → `ollama create followup-summary`.
4. `[ ]` 7.4 Evaluate base vs fine-tuned vs teacher with the Step 4 harness; CPU latency and tokens.
5. `[ ]` 7.5 `docs/model_cards/summary_qlora.md`; adapter and GGUF published to Hugging Face Hub.

**Artifact.** Adapter, GGUF, Modelfile, model card, comparison table in `docs/eval_reports/summary.md`.

**Verify.** Gateway config switch to `followup-summary` passes the same `make eval-summary`.

---

## Step 8 — Privacy boundary and responsible AI `[ ]`

**Goal.** Make the safety properties testable and documented.

1. `[ ]` 8.1 Gateway-only rule enforced by a test that greps imports.
2. `[ ]` 8.2 De-identification tests: names, phones, NIN, exact dates, addresses in any field → refusal.
3. `[ ]` 8.3 `audit_events` for summary views, worklist changes, call results.
4. `[ ]` 8.4 `docs/responsible_ai.md` completed with fairness numbers, failure modes, opt-out, NDPA 2023 and HIPAA Safe Harbor references.
5. `[ ]` 8.5 Human-in-the-loop checklist verified per feature.

**Verify.** `pytest tests/test_privacy_boundary.py` green; document reviewed.

---

## Step 9 — MLOps for low-bandwidth settings `[ ]`

1. `[ ]` 9.1 MLflow registry directory; `model_version` on every score and summary.
2. `[ ]` 9.2 Prompt files versioned; version recorded per request.
3. `[ ]` 9.3 GitHub Actions: pytest + promptfoo regression; factuality thresholds fail the build.
4. `[ ]` 9.4 `/health`, `/metrics` (Prometheus) with score distribution, PII refusals, check failures, unsafe intents, p95 latency.
5. `[ ]` 9.5 Weekly drift report task.
6. `[ ]` 9.6 `make bundle`: offline Compose bundle with pre-pulled weights; RAM footprint table per model.

**Verify.** CI green on a PR; `make bundle` runs with network disabled.

---

## Step 10 — Frontend: four screens `[ ]`

1. `[ ]` 10.1 Worklist screen with one-tap call result and basis badge.
2. `[ ]` 10.2 Patient view: facts, BP sparkline, drugs, summary, feedback link, reckoner panel.
3. `[ ]` 10.3 Chat simulator: patient SMS view and staff view with detected intent/state.
4. `[ ]` 10.4 Evaluation dashboard reading `docs/eval_reports` and MLflow.

**Verify.** `npm run build` passes; walkthrough of all four screens against seeded data.

---

## Step 11 — Documentation and pitch package `[ ]`

1. `[ ]` 11.1 README: GIF, `make up && make seed && make eval`, table of contents.
2. `[ ]` 11.2 `docs/pitch.md`: one section per RTSL use case with screen, metric, file path; "How this integrates with Simple".
3. `[ ]` 11.3 6–8 minute recorded walkthrough.
4. `[ ]` 11.5 Technical write-up (identity-free summaries, or cold-start partial pooling).

**Verify.** A reader can run the demo from README alone in under 15 minutes.

---

## Progress log

| Date | Step | Note |
| --- | --- | --- |
| 2026-09-26 | 0 | Repository initialized, tracker and ADRs written. |
| 2026-09-26 | 1 | Simple-shaped schema (12 tables, 6 views) migrated into local `d_clinic`; synthetic generator (6,000 patients) loaded; 11 invariant tests green; EDA notebook executed. Generator tuned twice: return-to-care probabilities raised (overdue 67% → 48%), lead-time effect strengthened so >60 d is the riskiest band. |
| 2026-09-26 | 2 | Feature pipeline with leakage test (caught and fixed a facility-rate leak); rules vs logistic vs boosting with strict patient+time split; logistic selected (test AUC 0.648, lift 1.49 at 30% capacity, ceiling 0.70); partial-pooling cold start; fairness notebook with bootstrap; model card; `risk_scores` table, API endpoints, Celery nightly task; 31 tests green. |
