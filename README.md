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

## Running

Populated in Step 1 (`make up && make seed`).

## Licence

MIT — see [`LICENSE`](LICENSE).
