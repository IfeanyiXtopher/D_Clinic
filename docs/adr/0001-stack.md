# ADR-0001: Technology stack

**Status:** Accepted — 2026-09-26

## Context

The product is an AI follow-up layer for a hypertension/diabetes program,
intended to sit beside Simple (Ruby on Rails + PostgreSQL backend, Kotlin
Android app). The primary audience for the MVP is an applied-ML/LLM hiring
panel. Constraints: free and open-source only (an existing OpenAI key may be
used as an optional provider), must run offline on a laptop after setup,
identity must never reach a model.

## Decision

- **Python 3.12 + FastAPI** for the API and model-serving endpoints.
- **PostgreSQL (pgvector image)** with tables named after Simple's public
  schema so integration is a mapping exercise, not a redesign.
- **SQLAlchemy 2 + Alembic** for models and migrations.
- **Celery + Redis** for nightly scoring, worklist generation, reminder
  queueing, and scheduled evaluation runs.
- **Pandas / NumPy / scikit-learn / LightGBM** for features and the risk model.
- **PyTorch + Hugging Face Transformers + PEFT (QLoRA)** for fine-tuning;
  free compute on Kaggle (30 GPU h/week) or Colab.
- **Ollama** (llama.cpp under the hood, OpenAI-compatible API) to serve
  quantized GGUF models locally. **vLLM** deferred until a GPU host exists.
- **Microsoft Presidio** for second-line PII detection.
- **MLflow** (local SQLite backend) for experiment tracking and versioning.
- **promptfoo**, **DeepEval/RAGAS** for LLM evaluation in CI.
- **React + Vite + TypeScript** for four screens.
- **Docker Compose** for local and offline deployment.

## Alternatives considered

- *Django + DRF.* Better for a full clinic product with admin screens. Rejected
  here because the deliverable is an AI service; FastAPI keeps the code
  closer to what the role evaluates and is the natural home for model
  endpoints. Revisit if the product grows a large operational back-office.
- *LangChain / LlamaIndex.* Rejected for the MVP: thin wrappers hide the
  prompt and retrieval logic that we want to show and test directly.
- *Separate vector database.* Rejected; pgvector keeps one database.

## Consequences

- One repo, one Compose file, no cloud dependency.
- Rails-side integration later means writing an exporter from Simple's tables
  to ours, or pointing our read models at a Simple replica.
