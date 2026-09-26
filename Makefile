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

.PHONY: help venv up down migrate synth seed test eda
