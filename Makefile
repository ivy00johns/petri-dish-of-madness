# Makefile — PetriDishOfMadness convenience targets
# See README.md for the full quickstart guide.

.PHONY: help dev up down build install install-backend install-frontend \
        lint test validate venv

# ── Configuration ─────────────────────────────────────────────────────────────
# Interpreter used to create the project virtualenv. Must be Python 3.11+.
# Bare `python`/`pip` on macOS often point at the wrong (or externally-managed)
# Homebrew Python, so the backend always installs into a repo-local .venv.
# Override on the CLI, e.g.  make install PYTHON=python3.13
PYTHON  ?= python3.12
VENV    := .venv
VENV_PY := $(CURDIR)/$(VENV)/bin/python

# ── Default target ────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  PetriDishOfMadness — available targets"
	@echo ""
	@echo "  Local dev (no Docker):"
	@echo "    make dev              Start backend + frontend together (same as ./dev)"
	@echo "    make install          Create .venv + install Python pkg + Node deps"
	@echo "    make install-backend  Create .venv (Python 3.11+) + pip install -e backend"
	@echo "    make install-frontend cd web && npm install"
	@echo ""
	@echo "  Docker:"
	@echo "    make up               docker compose up --build"
	@echo "    make down             docker compose down"
	@echo "    make build            docker compose build"
	@echo ""
	@echo "  Quality:"
	@echo "    make validate         Validate configs and scripts"
	@echo "    make test             Run backend test suite"
	@echo ""

# ── Local dev ─────────────────────────────────────────────────────────────────
dev:
	./dev

install: install-backend install-frontend

# Create the virtualenv on demand (only when it doesn't already exist).
venv: $(VENV_PY)
$(VENV_PY):
	$(PYTHON) -m venv $(VENV)
	$(VENV_PY) -m pip install --upgrade pip

install-backend: $(VENV_PY)
	$(VENV_PY) -m pip install -e backend

install-frontend:
	cd web && npm install

# ── Docker ────────────────────────────────────────────────────────────────────
up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

# ── Quality ───────────────────────────────────────────────────────────────────
validate:
	@echo "==> docker compose config"
	docker compose config --quiet && echo "  OK"
	@echo "==> dev script syntax"
	bash -n ./dev && echo "  OK (bash)"
	zsh -n ./dev && echo "  OK (zsh)"
	@echo "==> YAML: config/profiles.yaml"
	$(VENV_PY) -c "import yaml,sys; yaml.safe_load(open('config/profiles.yaml'))" && echo "  OK"
	@echo "==> YAML: config/world.yaml"
	$(VENV_PY) -c "import yaml,sys; yaml.safe_load(open('config/world.yaml'))" && echo "  OK"

test:
	cd backend && $(VENV_PY) -m pytest
