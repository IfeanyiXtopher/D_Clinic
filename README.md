# Followup-AI

An open-source **AI follow-up layer for a hypertension and diabetes program**,
shaped to sit beside [Simple](https://docs.simple.org/) (Resolve to Save
Lives). It reads Simple-style tables (patients, blood pressures, blood sugars,
prescriptions, appointments, call results, SMS communications) and adds:

- a **risk model** for missed follow-up, with a cold-start path for new patients,
- an **optimized daily worklist** for frontline health workers,
- a **patient summary** written by a locally runnable LLM from structured data,
- a **scheduling chatbot** that works over SMS-style text,
- a **ready-reckoner** that answers protocol questions from WHO HEARTS with citations.

Everything runs on synthetic patients, offline after setup, with identity kept
out of every prompt, and every AI feature ships with a written evaluation.

**Build status and step-by-step progress:** see [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).

## Layout

```text
D_Clinic_Backend/   FastAPI app, ML, LLM gateway, chatbot, reckoner, Celery worker
D_Clinic_Frontend/  React + Vite + TypeScript (four screens)
data/synth/         synthetic cohort generator and sample CSVs
data/protocols/     WHO HEARTS and national hypertension protocol text
data/eval_sets/     gold Q&A, must-keep facts, scripted chatbot dialogues
notebooks/          EDA, modelling, fairness, summary evaluation, fine-tuning
eval/               promptfoo configs and evaluation runner
docs/               build plan, ADRs, model cards, evaluation reports, responsible AI
```

## Running (through Step 3)

Prerequisites: Python 3.11+, Docker, and a PostgreSQL database you can reach
(or use the containerised one).

```bash
cp .env.example .env            # set PG_* to your database
make venv                       # virtualenv + backend deps
make up                         # redis  (add PROFILE=db for a PostgreSQL+pgvector container)
make seed                       # migrate, generate 6,000 synthetic patients, load
make train                      # missed-visit model + report
make score                      # score upcoming appointments
make eval-worklist              # replay risk vs days-overdue worklists
make test                       # 41 tests (generator, features, cold start, risk API, worklist)
make api                        # FastAPI on :8000
```

Useful endpoints: `GET /worklist?facility_id=&date=`, `POST /call-results`, `POST /risk/score`.
Program definitions are in [`docs/definitions.md`](docs/definitions.md).
The worklist replay report is [`docs/eval_reports/worklist.md`](docs/eval_reports/worklist.md).

## Licence

MIT — see [`LICENSE`](LICENSE).
