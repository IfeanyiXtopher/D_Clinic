.DEFAULT_GOAL := help
VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
BACKEND := D_Clinic_Backend

help:  ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

venv:  ## Create virtualenv and install backend (+dev, +ml)
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e "$(BACKEND)[dev,ml]"

up:  ## Start local infrastructure (redis; add PROFILE=db for a containerised PostgreSQL)
	docker compose $(if $(PROFILE),--profile $(PROFILE),) up -d

down:  ## Stop local infrastructure
	docker compose --profile db down

migrate:  ## Apply database migrations
	cd $(BACKEND) && ../$(PY) -m alembic upgrade head

synth:  ## Generate the synthetic cohort CSVs only
	$(PY) data/synth/generate.py --patients $${SYNTH_PATIENTS:-6000} --seed $${SYNTH_SEED:-42}

seed: migrate  ## Generate synthetic cohort and load it into PostgreSQL (idempotent)
	cd $(BACKEND) && ../$(PY) -m scripts.seed

test:  ## Run backend tests
	cd $(BACKEND) && ../$(PY) -m pytest -q

eda:  ## Execute the EDA notebook in place
	$(PY) -m jupyter nbconvert --to notebook --execute --inplace notebooks/01_eda.ipynb

eval-worklist:  ## Replay risk vs days-overdue worklists; write docs/eval_reports/worklist.md
	cd $(BACKEND) && LOKY_MAX_CPU_COUNT=4 ../$(PY) -m ml.worklist_eval

train:  ## Train the missed-visit model from the database; write artifact, report, MLflow run
	cd $(BACKEND) && LOKY_MAX_CPU_COUNT=4 ../$(PY) -m ml.train

score:  ## Score upcoming appointments (next 60 days) and persist to risk_scores
	cd $(BACKEND) && LOKY_MAX_CPU_COUNT=4 ../$(PY) -c "from app.db import engine; from ml.predict import score_upcoming, write_scores; s=score_upcoming(engine); print('scored', write_scores(s, engine)); print(s.band.value_counts().to_dict())"

notebooks:  ## Rebuild and execute the modelling and fairness notebooks
	$(PY) notebooks/build_02_03.py
	for n in 02_missed_visit_model 03_fairness_and_calibration; do \
	  LOKY_MAX_CPU_COUNT=4 $(PY) -m jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=600 notebooks/$$n.ipynb; done

api:  ## Run the FastAPI app on :8000
	cd $(BACKEND) && ../$(PY) -m uvicorn app.main:app --reload --port 8000

worker:  ## Run a Celery worker (needs redis: make up)
	cd $(BACKEND) && ../$(PY) -m celery -A worker.celery_app worker -l info

beat:  ## Run the Celery beat scheduler (exactly one instance)
	cd $(BACKEND) && ../$(PY) -m celery -A worker.celery_app beat -l info

mlflow:  ## Open the MLflow UI on :5000
	$(PY) -m mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5000

.PHONY: help venv up down migrate synth seed test eda eval-worklist train score notebooks api worker beat mlflow
