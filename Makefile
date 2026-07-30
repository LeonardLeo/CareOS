.DEFAULT_GOAL := help
API := services/api
VENV := $(API)/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Create the venv and install the API with dev extras
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e "$(API)[dev]"

.PHONY: bootstrap-db
bootstrap-db: ## Create the local database and the careos_app / careos_auth roles
	psql -h localhost -U postgres -c "CREATE DATABASE careos" || true
	psql -h localhost -U postgres -d careos -v ON_ERROR_STOP=1 -f $(API)/scripts/bootstrap_db.sql

.PHONY: migrate
migrate: ## Apply all migrations
	cd $(API) && .venv/bin/alembic upgrade head

.PHONY: seed
seed: ## Seed global reference data (EVV aggregators, credential types, service codes)
	cd $(API) && .venv/bin/python -m careos.scripts.seed_reference_data

.PHONY: dev
dev: ## Run the API with reload
	cd $(API) && .venv/bin/uvicorn careos.main:app --reload --port 8000

# These invoke `pytest` rather than `python -m pytest` to match CI exactly. The two forms
# differ in what lands on sys.path, and running the friendlier one locally hid a collection
# failure that only CI saw.
.PHONY: test
# CAREOS_TEST_REDIS_URL is what un-skips the shared rate-limit store's tests. Point it at a
# Redis you do not mind being written to; the tests namespace their own keys and clean up after
# themselves, but they do write. Without it the module skips and the rest of the suite runs.
test: ## Run the full test suite (requires PostgreSQL; set CAREOS_TEST_REDIS_URL for the shared limiter)
	cd $(API) && CAREOS_ENVIRONMENT=test .venv/bin/pytest -q

.PHONY: test-isolation
test-isolation: ## Run only the multi-tenant isolation tests
	cd $(API) && CAREOS_ENVIRONMENT=test .venv/bin/pytest tests/test_multitenant_isolation.py -v

# Reproduces CI rather than approximating it. Three separate CI failures came from code that
# assumed a developer machine: a source directory excluded by .gitignore, `python -m pytest`
# resolving imports differently from `pytest`, and a hard-coded services/api/.venv/bin/alembic.
# None were visible from a working tree that already had all three. This target builds a clean
# clone with its virtualenv outside the repo, which is the only arrangement in which those
# assumptions fail here the way they fail there.
.PHONY: test-clean
test-clean: ## Run the suite against a clean clone with an out-of-tree venv, as CI does
	@set -e; \
	tmp=$$(mktemp -d); \
	echo "clean checkout: $$tmp"; \
	git clone -q --depth 1 --no-local . $$tmp/repo; \
	python3 -m venv $$tmp/venv; \
	$$tmp/venv/bin/pip install -q --upgrade pip "setuptools>=83.0.0"; \
	$$tmp/venv/bin/pip install -q -e "$$tmp/repo/services/api[dev]"; \
	cd $$tmp/repo/services/api && CAREOS_ENVIRONMENT=test $$tmp/venv/bin/pytest -q; \
	status=$$?; rm -rf $$tmp; exit $$status

.PHONY: lint
lint: ## Lint and format-check
	cd $(API) && .venv/bin/ruff check careos tests
	cd $(API) && .venv/bin/ruff format --check careos tests

.PHONY: fix
fix: ## Auto-fix lint and formatting
	cd $(API) && .venv/bin/ruff check --fix careos tests
	cd $(API) && .venv/bin/ruff format careos tests

.PHONY: typecheck
typecheck: ## Static type check
	cd $(API) && .venv/bin/mypy careos

.PHONY: check
check: lint typecheck test ## Everything CI runs

.PHONY: up
up: ## Start the local stack in Docker
	docker compose up --build

.PHONY: down
down: ## Stop the local stack
	docker compose down -v
