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

> **Step 11 — Documentation and pitch: `[x]` done.** Walkthrough *recording* is the presenter (script in `docs/walkthrough.md`).

## Prerequisites on the developer machine

| Tool | Needed from | Installed |
| --- | --- | --- |
| Python 3.11+ | Step 1 | yes (3.12.0) |
| Docker + Compose | Step 1 | yes (29.4) |
| Node 20+ | Step 10 | yes (24.15) |
| Ollama | Step 4 (local) | **optional** — laptop only; `LLM_PROVIDER=ollama` after `ollama pull qwen2.5:3b` |
| pgvector extension | Step 6 | **optional** — host PG18 has no pgvector; TF-IDF joblib index is the retriever. `make up PROFILE=db` if you want the extension later |
| Kaggle account | Step 7 | for free T4/P100 fine-tuning |
| OpenAI API key (optional) | Step 4 live, Step 7 | live MVP on a small VPS (`LLM_PROVIDER=openai`); teacher model later |

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

## Step 3 — Optimized worklist for frontline workers `[x]`

**Goal.** A ranked, capacity-limited, explainable daily list that beats
"sort by days overdue" on extra returns per call.

1. `[x]` 3.1 `ml/worklist.py`: eligibility as of a date (skip `agreed_to_visit` < 15 days; resurface `remind_to_call_later` on `remind_on` or +7 days; drop removals and LTFU; phone-first ranking). Capacity default 20 with 25% protected slots for uncontrolled BP. Pre-visit section: up to 5 high-risk visits in the next 7 days.
2. `[x]` 3.2 `GET /worklist?facility_id=&date=&rebuild=` returns overdue + pre-visit items with rank, band, basis, reasons, suggested action (`call` / `call_back` / `home_visit` / `reminder_call`). Identity fields are never in the payload. `worklist_items` table (migration 0004); rebuild keeps items that already have a call result.
3. `[x]` 3.3 `POST /call-results` with Simple's exact `result_type` / `remove_reason`. Updates the appointment (`agreed_to_visit`, `remind_on`, or cancel + patient status) and closes the worklist item. `POST /worklist/items/{id}/skip`.
4. `[x]` 3.4 Celery Beat `build-daily-worklists` at 06:00 Africa/Lagos; first GET builds on demand. Idempotent: a second beat run is a no-op unless `rebuild=true`.
5. `[x]` 3.5 Replay (`ml/worklist_eval.py`): weekly snapshots on the **test-pool** only, capacity 25/facility-week. Strategies: days-overdue, random, risk, oracle. Headline metric is **counterfactual extra returns per 100 calls** (using the generator's known return functions), with an observational 15-day return table for transparency.

**Artifact.** Worklist API + persistence; `docs/eval_reports/worklist.md`; 10 worklist tests.

**Verify.** `make eval-worklist` writes the report; `make test` → 41 passed.

**Measured on 2026-09-27 (15 weeks, test pool).** Extra returns per 100 calls: days-overdue **18.2**, random 18.5, **risk 20.9 (+15%)**, oracle 27.1. Bootstrap of risk − days-overdue: **+2.7 [+2.2, +3.3]**. List overlap 36%. Observational 15-day return among those actually called that week: risk 44% (n=95) vs random 39% (n=76); longest-overdue selections were almost never called in the data (they are months late). Side effect logged: cold-start patients are 5% of the risk list vs 17% of longest-overdue-first — protect slots for new patients if the program wants that.

**Also in this step.** Generator return-to-care probabilities are now explicit functions of the hidden propensity (`p_return_after_call` / `p_return_no_call`) so the replay has a known counterfactual. Leakage test updated: same-day visit BP is allowed at booking; injected events must fall on a later calendar day.

---

## Step 4 — Patient summary for the health worker `[x]`

**Goal.** Five-line summary from structured data, generated by a local model,
with identity stripped and every number checked against the source.

1. `[x]` 4.1 `llm/deid.py` packet builder (age band, sex, relative dates, BP/BS history, drugs, attendance, call outcome, risk band + basis). Refuses on any PII.
2. `[x]` 4.2 Presidio scan inbound and outbound (pattern recognisers when the `llm` extra is installed; regex always).
3. `[x]` 4.3 `llm/gateway.py`: one provider interface (`none` / `ollama` / `openai`); versioned prompt `summary_v1`; `llm_requests` audit table (migration 0005). Same OpenAI-shaped `/v1` call; switching live vs laptop is `.env` only.
4. `[x]` 4.4 Post-check: every number and drug name in output must exist in packet; else fall back to templated summary and log.
5. `[x]` 4.5 `POST /patients/{id}/summary` returning structured facts + summary + check status.
6. `[x]` 4.6 Evaluation: 200 packets with `data/eval_sets/must_keep_facts.json`; factuality, omission, length, PDSQI-9-style rubric → `docs/eval_reports/summary.md`; `notebooks/04_summary_eval.ipynb`.
7. `[x]` 4.7 Static test: no module outside `llm/gateway.py` imports an LLM client.

**Artifact.** Summary endpoint, evaluation report, prompt v1.

**Verify.** `pytest tests/test_deid.py` includes a fixture with a phone number in a note and asserts refusal; `make eval-summary` writes the report.

**Measured on 2026-09-27 (200 packets).** Template factuality 1.00, omission 0.00, PDSQI-9-style mean 1.00, PII rate 0. A sloppy model that invents BP 200/130, Losartan and a name fails the check; the pipeline falls back on 100% of those packets and recovers template quality. Live Ollama/OpenAI is optional (`LLM_PROVIDER=none` uses the template — the 1 GB VPS path).

---

## Step 5 — Scheduling chatbot over SMS-style text `[x]`

**Goal.** Confirm, reschedule, or cancel a visit through short text messages.
The LLM classifies; the state machine and tools decide.

1. `[x]` 5.1 Dialogue state machine: `idle`, `confirming`, `choosing_slot`, `rescheduling`, `cancelling`, `handoff`.
2. `[x]` 5.2 Structured-output NLU via gateway JSON schema: `{intent, date_hint, time_hint, confirm, language, needs_human}`. Rules are the default (1 GB VPS); LLM when `LLM_PROVIDER` is set.
3. `[x]` 5.3 Tools in code: `get_available_slots`, `book`, `reschedule`, `cancel`, `record_reply`.
4. `[x]` 5.4 Templated replies; model may only rephrase; dates inserted by code after rephrase; Presidio/regex scan.
5. `[x]` 5.5 Safety: medical/symptom intent → fixed reply + staff call task; `stop` → consent off.
6. `[x]` 5.6 Channels: `POST /sms/inbound` simulator; `POST /sms/webhook` Africa's Talking sandbox shape; outbound stored on `communications`.
7. `[x]` 5.7 Small intent classifier: TF-IDF + logistic (`sms_intent_v1`) on synthetic SMS; compared with rules on accuracy and CPU latency. DistilBERT / Qwen 0.6B skipped (RAM; same reason as Ollama on the live VPS).
8. `[x]` 5.8 Evaluation: 150 scripted dialogues incl. Pidgin/Hausa/Yoruba and adversarial prompts → `docs/eval_reports/chatbot.md`. `eval/promptfoo/chatbot.yaml` + `python eval/promptfoo/run_chatbot.py`.

**Artifact.** Chatbot service, webhook, simulator, evaluation report, `docs/model_cards/sms_intent.md`.

**Verify.** `python eval/promptfoo/run_chatbot.py` (or `promptfoo eval -c eval/promptfoo/chatbot.yaml`) passes; `pytest tests/test_dialogue.py` green.

**Measured on 2026-09-27 (150 dialogues).** Intent 140/140 labelled turns; task completion 1.00; unsafe 0; PII 0. Rules accuracy 0.79 vs TF-IDF 0.76 on the synthetic SMS corpus (rules are faster and win, so they stay the default). 76 tests green.

---

## Step 6 — Ready-reckoner and on-the-job guidance `[x]`

**Goal.** Protocol answers with citations from WHO HEARTS and a national
hypertension protocol, plus a deterministic "next step" lookup.

1. `[x]` 6.1 Corpus in `data/protocols/` as text; chunk by protocol step (`hearts.md`, `national_htn.md` — educational adaptations, not official WHO/FMOH copies).
2. `[x]` 6.2 Retrieval: TF-IDF default (no API, fits a 2 GB VPS) in `reckoner/artifacts/protocol_tfidf_v1.joblib`. Optional dense path via `EMBEDDING_PROVIDER=ollama` (`nomic-embed-text`) or `openai` (`text-embedding-3-small`) — `make index-protocols DENSE=1`. pgvector is not required.
3. `[x]` 6.3 Retrieval top-4, extractive grounded answer (optional LLM rephrase via `reckoner_v1`), "not covered" refusal, dose post-check.
4. `[x]` 6.4 Structured mode: BP band × current drug → next step table (`reckoner/next_step.py`), used by Step 4 `suggested_next_step`.
5. `[x]` 6.5 Evaluation: 80 gold Q&A + 20 out-of-scope; recall@4, faithfulness, refusal accuracy → `docs/eval_reports/reckoner.md`.

**Artifact.** `POST /reckoner/ask`, `POST /reckoner/next-step`, evaluation report.

**Verify.** `make eval-reckoner` writes the report with recall@4 and faithfulness.

**Measured on 2026-09-27.** Recall@4 0.94; faithfulness 1.00 on answered items; OOS refusal 1.00; in-scope refusal 0.04; next-step table 5/5. 84 tests green.

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

## Step 8 — Privacy boundary and responsible AI `[x]`

**Goal.** Make the safety properties testable and documented.

1. `[x]` 8.1 Gateway-only rule enforced by `tests/test_privacy_boundary.py` (imports + provider URLs).
2. `[x]` 8.2 De-identification tests: names, phones, NIN, exact dates, addresses in any field → refusal.
3. `[x]` 8.3 `audit_events` (migration 0008) for summary views, worklist rebuild/skip, call results.
4. `[x]` 8.4 `docs/responsible_ai.md` completed with fairness numbers, failure modes, opt-out, NDPA 2023 and HIPAA Safe Harbor references.
5. `[x]` 8.5 Human-in-the-loop checklist verified per feature (`docs/hitl_checklist.md`).

**Artifact.** Privacy tests, `audit_events`, responsible-AI write-up, HITL checklist.

**Verify.** `pytest tests/test_privacy_boundary.py` green; `docs/responsible_ai.md` has no TBD.

---

## Step 9 — MLOps for low-bandwidth settings `[x]`

1. `[x]` 9.1 `ml/registry/registry.json`; `model_version` on every score and summary (`template` when no model).
2. `[x]` 9.2 Prompt files `summary_v1` / `nlu_v1` / `rephrase_v1` / `reckoner_v1`; version recorded on `llm_requests`.
3. `[x]` 9.3 `.github/workflows/ci.yml`: migrate + pytest + `make eval-gates` (factuality / unsafe / recall thresholds).
4. `[x]` 9.4 `/health` unchanged; `/metrics` Prometheus (score bands, PII refusals, check failures, unsafe intents, p95).
5. `[x]` 9.5 Celery `weekly_drift_report` (Sunday 03:00) → `docs/eval_reports/drift.md`.
6. `[x]` 9.6 `make bundle` copies local artifacts into `dist/offline-bundle/` (no network). RAM table in `docs/mlops.md`.

**Artifact.** Registry, CI workflow, `/metrics`, drift task, offline bundle target.

**Verify.** `make test` green; `make eval-gates` exits 0; `make bundle` writes `dist/offline-bundle/MANIFEST.txt`.

---

## Step 10 — Frontend: four screens `[x]`

1. `[x]` 10.1 Worklist: facility + date, risk rank, basis badge, one-tap Agreed / Call later / Skip.
2. `[x]` 10.2 Patient: facts, BP sparkline, drugs, checked summary, enum feedback, reckoner panel.
3. `[x]` 10.3 Chat simulator: patient SMS bubble view and staff intent/state + staff tasks.
4. `[x]` 10.4 Evaluation: registry table + eval report headlines and bodies (`GET /eval/reports`, `/eval/registry`).

**Artifact.** `D_Clinic_Frontend/` (Vite + React + TypeScript). Demo APIs: `/facilities`, `/demo/context`, `/eval/*`, `/patients/{id}/feedback`. API on **:8010** (this machine already binds :8000).

**Verify.** `cd D_Clinic_Frontend && npm run build` passes.

**Walked on 2026-09-27** against the seeded cohort (list date 2026-09-22): 25-row worklist with high/personal badges; summary `check=passed` and no identity; reckoner answered an amlodipine dose; SMS reminder → “I go come” confirmed; eval listed 6 reports; feedback and call-later returned 201. No browser tool in this session — routes and proxied APIs were exercised with curl.

---

## Step 11 — Documentation and pitch package `[x]`

1. `[x]` 11.1 README: demo figure (`docs/demo-flow.svg`), `make up && make seed && make eval`, table of contents.
2. `[x]` 11.2 `docs/pitch.md`: one section per RTSL-shaped use case with screen, metric, file path; Simple integration.
3. `[x]` 11.3 6–8 minute walkthrough **script** (`docs/walkthrough.md`). Record the video from that shot list.
4. `[x]` 11.5 Technical write-up: identity-free briefings (`docs/writeup-identity-free-summaries.md`).

**Artifact.** README, `docs/pitch.md`, `docs/walkthrough.md`, `docs/writeup-identity-free-summaries.md`, `docs/demo-flow.svg`, `make eval` / `make eval-all`.

**Verify.** A reader can run the demo from README alone in under 15 minutes (`make venv && make up && make seed && make eval && make api` / `make ui`).

---

## Progress log

| Date | Step | Note |
| --- | --- | --- |
| 2026-09-26 | 0 | Repository initialized, tracker and ADRs written. |
| 2026-09-26 | 1 | Simple-shaped schema (12 tables, 6 views) migrated into local `d_clinic`; synthetic generator (6,000 patients) loaded; 11 invariant tests green; EDA notebook executed. Generator tuned twice: return-to-care probabilities raised (overdue 67% → 48%), lead-time effect strengthened so >60 d is the riskiest band. |
| 2026-09-26 | 2 | Feature pipeline with leakage test (caught and fixed a facility-rate leak); rules vs logistic vs boosting with strict patient+time split; logistic selected (test AUC 0.648, lift 1.49 at 30% capacity, ceiling 0.70); partial-pooling cold start; fairness notebook with bootstrap; model card; `risk_scores` table, API endpoints, Celery nightly task; 31 tests green. |
| 2026-09-27 | 3 | Daily worklist with Simple eligibility rules, protected slots for uncontrolled BP, call-result API, 06:00 Celery build. Replay: risk ranking +15% extra returns per 100 calls vs longest-overdue-first (+2.7 [+2.2, +3.3]); 41 tests green. |
| 2026-09-27 | 4 | De-id packet, Presidio/regex scan, gateway (`none`/`ollama`/`openai`), number/drug post-check, templated fallback, `POST /patients/{id}/summary`, `llm_requests` audit. 200-packet eval: template factuality 1.00, sloppy model 100% fallback. 58 tests green. |
| 2026-09-27 | 5 | SMS state machine (LLM understands, code decides). Simulator + Africa's Talking webhook. Medical → staff task; STOP → consent off. 150 dialogues: intent 100%, task 100%, unsafe 0, PII 0. 76 tests green. |
| 2026-09-27 | 6 | HEARTS / PHC protocol chunks, TF-IDF retrieval (pgvector optional), extractive answers + dose check, next-step table wired into summaries. Eval: recall@4 0.94, faithfulness 1.00, OOS refusal 1.00. 84 tests green. |
| 2026-09-27 | 6b | Dual embeddings: `EMBEDDING_PROVIDER=tfidf` (default) / `ollama` / `openai`. Same gateway as chat. Dense index only with `make index-protocols DENSE=1`; query falls back to TF-IDF if the embed call fails. |
| 2026-09-27 | 7 | Skipped for live: QLoRA/GGUF would not run on the VPS. |
| 2026-09-27 | 8 | Privacy tests (name/phone/NIN/date/address), `audit_events`, responsible-AI + HITL docs. |
| 2026-09-27 | 9 | Registry, `/metrics`, weekly drift, `make eval-gates` + GitHub Actions, `make bundle`. |
| 2026-09-27 | 10 | Four screens (worklist, patient, SMS, eval). Vite on :5173, API on :8010. `npm run build` green. |
| 2026-09-27 | 11 | README 15-minute path, pitch (Simple + use cases), walkthrough script, identity-free briefing write-up. Recording left to the presenter. |
