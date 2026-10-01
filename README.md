# Followup-AI

An open-source **AI follow-up layer** for a hypertension and diabetes program,
shaped to sit beside [Simple](https://docs.simple.org/) (Resolve to Save
Lives). It is not a clinic EHR and it does not prescribe.

![Worklist, briefing, SMS, protocol](docs/demo-flow.svg)

- Rank the daily **call list** (a score never removes anyone)
- Open a **case briefing** checked against the record
- Let the patient **confirm or move** a visit by SMS
- Look up **HEARTS / PHC** text with a citation

Identity never enters a model prompt. Every surface has a written evaluation.

## Contents

1. [15-minute demo](#15-minute-demo)
2. [Screens](#screens)
3. [Pitch and write-ups](#pitch-and-write-ups)
4. [Layout](#layout)
5. [Optional LLM](#optional-llm)
6. [Licence](#licence)

## 15-minute demo

Needs Python 3.11+, Docker (Redis), PostgreSQL you can reach, and Node 20+ for
the UI.

```bash
cp .env.example .env          # set PG_HOST, PG_DB, PG_USER, PG_PASSWORD
make venv
make up                       # Redis
make seed                     # migrate + 6,000 synthetic patients
make eval                     # CI gates on the published reports
make api                      # http://127.0.0.1:8010
make ui                       # http://127.0.0.1:5173  (proxies /api → :8010)
```

Worklist date for this seed: **2026-09-22**. If the model artifact is missing,
run `make train && make score` once (longer than 15 minutes).

`make eval-all` regenerates worklist / summary / SMS / protocol reports.

## Screens

| Route | What the worker does |
| --- | --- |
| `/` | Today’s follow-up list — overdue and pre-visit |
| `/patients/:id` | Briefing, staff rating, protocol next step and Q&A |
| `/chat` | SMS reminder and replies (simulator) |
| `/eval` | How the program is run and checked |

Walkthrough shot list (6–8 min recording): [`docs/walkthrough.md`](docs/walkthrough.md).

## Pitch and write-ups

| Doc | What it is |
| --- | --- |
| [`docs/pitch.md`](docs/pitch.md) | One RTSL-shaped use case per screen, metrics, file paths, Simple integration |
| [`docs/writeup-identity-free-summaries.md`](docs/writeup-identity-free-summaries.md) | How briefings stay identity-free and checked |
| [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) | Build tracker |
| [`docs/responsible_ai.md`](docs/responsible_ai.md) | Purpose, limits, HITL |
| [`docs/definitions.md`](docs/definitions.md) | Visit, overdue, call results (Simple vocabulary) |

## Layout

```text
D_Clinic_Backend/   API, model, briefing gateway, SMS, protocol lookup, worker
D_Clinic_Frontend/  Four screens (Vite + React)
data/synth/         Cohort generator
data/protocols/     HEARTS / PHC text
data/eval_sets/     Gold Q&A and scripted dialogues
docs/               Pitch, eval reports, ADRs, model cards
```

## Optional LLM

Default `.env` runs without a hosted model (`LLM_PROVIDER=none`). To use a
key you already have:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

Restart the API after changing `.env`. Protocol search stays local TF-IDF unless
you set `EMBEDDING_PROVIDER` and rebuild the index.

## Licence

MIT — [`LICENSE`](LICENSE).
