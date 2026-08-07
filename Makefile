# ---------------------------------------------------------------------------
# Aleph — developer entrypoints.
#
# Every target here is the same command CI runs, so "works on my machine" and
# "passes CI" cannot drift apart. Nothing in this file is required to build or
# deploy the project; it exists so the checks are cheap to run locally.
# ---------------------------------------------------------------------------

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Prefer the project venv when it exists, fall back to the ambient interpreter
# so a fresh clone can still run `make install`.
PY := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
PIP := $(PY) -m pip

FRONTEND := frontend

# GitHub Pages serves the site from a subpath. Override for other hosts:
#   make build VITE_BASE=/
VITE_BASE ?= /Aleph/
# Empty means "no live API": the site reads the committed static JSON payload.
VITE_ALEPH_API_URL ?=

# Extra arguments forwarded to the pipeline, e.g. `make data ARGS="--force"`.
ARGS ?=

# Local Node toolchain, when one is vendored. Never referenced by CI or by
# anything that ships.
ifneq ($(wildcard .toolchain/bin/node),)
export PATH := $(CURDIR)/.toolchain/bin:$(PATH)
endif

.PHONY: help install dev api test lint fmt schemas data build docker clean

help:
	@echo "Aleph targets"
	@echo ""
	@echo "  install   install the Python package (api+dev extras) and frontend deps"
	@echo "  dev       run the API and the Vite dev server together"
	@echo "  api       run the API alone with autoreload"
	@echo "  test      run the Python test suite"
	@echo "  lint      ruff check + ruff format --check + eslint"
	@echo "  fmt       apply ruff autofixes and formatting"
	@echo "  schemas   compile every JSON Schema and validate the committed data"
	@echo "  data      regenerate the static analysis payload (ARGS=\"--force\")"
	@echo "  build     production frontend build (VITE_BASE=$(VITE_BASE))"
	@echo "  docker    build the container images"
	@echo "  clean     remove caches and build output"

# ---------------------------------------------------------------------------
install:
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[api,dev]'
	cd $(FRONTEND) && if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ---------------------------------------------------------------------------
dev:
	@echo "API      http://127.0.0.1:8000/v1/health"
	@echo "Frontend http://127.0.0.1:5173"
	@echo "Ctrl-C stops both."
	@trap 'kill 0' EXIT INT TERM; \
	 $(PY) -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 & \
	 ( cd $(FRONTEND) && npm run dev -- --host 127.0.0.1 --port 5173 ) & \
	 wait

api:
	$(PY) -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

# ---------------------------------------------------------------------------
test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	cd $(FRONTEND) && npm run lint

fmt:
	$(PY) -m ruff check . --fix
	$(PY) -m ruff format .

# ---------------------------------------------------------------------------
# A schema that does not compile is an unenforced contract, so this checks the
# schemas themselves before validating any instance against them.
schemas:
	$(PY) scripts/validate_schemas.py
	$(PY) scripts/validate_data.py
	$(PY) scripts/validate_design_tokens.py

# ---------------------------------------------------------------------------
data:
	$(PY) scripts/refresh.py $(ARGS)

build:
	mkdir -p $(FRONTEND)/public/data/schemas
	cp schemas/*.json $(FRONTEND)/public/data/schemas/
	cd $(FRONTEND) && VITE_BASE='$(VITE_BASE)' VITE_ALEPH_API_URL='$(VITE_ALEPH_API_URL)' npm run build

docker:
	docker compose build
	@echo "Built. Start the stack with: docker compose up"

# ---------------------------------------------------------------------------
clean:
	rm -rf build ./*.egg-info .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
	rm -rf $(FRONTEND)/dist $(FRONTEND)/.vite
	find . -path ./.venv -prune -o -path ./.toolchain -prune -o \
	     -path ./node_modules -prune -o -name '__pycache__' -type d -print0 \
	  | xargs -0 --no-run-if-empty rm -rf
