# Makefile — EmergenceMadness convenience targets
# See README.md for the full quickstart guide.

.PHONY: help dev up down build install install-backend install-frontend \
        lint test validate

# ── Default target ────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  EmergenceMadness — available targets"
	@echo ""
	@echo "  Local dev (no Docker):"
	@echo "    make dev              Start backend + frontend together (same as ./dev)"
	@echo "    make install          Install Python pkg + Node deps"
	@echo "    make install-backend  pip install -e backend"
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

install-backend:
	pip install -e backend

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
	python -c "import yaml,sys; yaml.safe_load(open('config/profiles.yaml'))" && echo "  OK"
	@echo "==> YAML: config/world.yaml"
	python -c "import yaml,sys; yaml.safe_load(open('config/world.yaml'))" && echo "  OK"

test:
	cd backend && python -m pytest
