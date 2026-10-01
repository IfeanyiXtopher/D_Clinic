# MLOps for a low-bandwidth host (Step 9)

## Registry

Production pointers live in `D_Clinic_Backend/ml/registry/registry.json`.
MLflow tracking (when `make train` can import mlflow) writes to `mlflow.db`
at the repo root. The live API does not need MLflow running.

| name | production version | recorded on |
| --- | --- | --- |
| missed_visit_risk | `missed_visit_v1` | every `risk_scores.model_version` |
| sms_intent | `sms_intent_v1` | chatbot artifact |
| worker_summary | `template` (or gateway model) | `llm_requests.prompt_version` + summary `model_version` |

Prompts are files in `D_Clinic_Backend/llm/prompts/`: `summary_v1`, `nlu_v1`,
`rephrase_v1`, `reckoner_v1`. `complete()` records `prompt_version` on every
`llm_requests` row.

## RAM footprint (offline bundle)

Figures are resident-set order of magnitude on a 2 GB VPS. They are not a
benchmark.

| component | typical RAM | needed on live VPS? |
| --- | --- | --- |
| FastAPI + Postgres client | 80–150 MB | yes |
| Redis (Docker) | 10–30 MB | if Celery is used |
| missed-visit joblib (logistic) | 20–40 MB when loaded | yes, for `/risk` and worklist |
| protocol TF-IDF joblib | 5–15 MB | yes, for `/reckoner` |
| sms_intent TF-IDF joblib | 5–10 MB | optional (rules are default) |
| OpenAI HTTP client | negligible | live chat/embeddings only |
| Ollama `qwen2.5:3b` | ~2–3 GB | **no — laptop only** |
| Ollama `nomic-embed-text` | ~500 MB | **no — laptop only** |
| QLoRA / GGUF (Step 7) | same class as Ollama | **no — not on live** |

Default live path: `LLM_PROVIDER=none` or `openai`, `EMBEDDING_PROVIDER=tfidf`
or `openai`. Do not pull Ollama weights onto the VPS.

## Offline bundle

`make bundle` copies local artifacts and this file into `dist/offline-bundle/`
and writes `MANIFEST.txt`. It does not download images or models.

To run later without the network: use the host Postgres you already have,
`docker compose up -d` only if Redis was already pulled, `LLM_PROVIDER=none`,
`EMBEDDING_PROVIDER=tfidf`.

## Drift

Celery beat Sundays 03:00 Africa/Lagos runs `weekly_drift_report` and writes
`docs/eval_reports/drift.md`. Alert if mean `p_missed` moves by ≥ 0.05 week
on week. An alert is for operators; it does not change thresholds.

## CI gates

`.github/workflows/ci.yml` runs pytest and `make eval-gates`. The build fails
if summary factuality &lt; 0.99, chatbot unsafe or PII &gt; 0, reckoner
recall@4 &lt; 0.85, faithfulness &lt; 0.99, or out-of-scope refusal &lt; 0.99.
