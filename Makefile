.PHONY: dev test lint format migrate seed audit debt-check debt-report debt-issues-dry-run backup-db restore-db help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

dev: ## Start local dev (DB + API)
	docker compose up db -d
	uv run fastapi dev src/nic/main.py

test: ## Run unit tests with coverage
	uv run pytest -m unit --cov=src/nic --cov-report=term -v

test-all: ## Run all tests
	uv run pytest -v

lint: ## Run linting and type checks
	uv run ruff check src/ tests/ scripts/
	uv run ruff format --check src/ tests/ scripts/
	uv run mypy src/nic/ --ignore-missing-imports

format: ## Auto-format code
	uv run ruff check --fix src/ tests/ scripts/
	uv run ruff format src/ tests/ scripts/

migrate: ## Run Alembic migrations
	uv run alembic upgrade head

seed: ## Upload images and auto-cluster (pass DIR=path)
	python scripts/seed.py $(DIR)

audit: ## Run dependency vulnerability scan
	uv run pip-audit

debt-check: ## Validate 148-row debt register integrity
	python3 scripts/debt_sync.py validate --strict --owner masa-57 --repo NIC

debt-report: ## Generate debt summary report artifacts
	python3 scripts/debt_sync.py report --out-dir docs/audit/reports

debt-issues-dry-run: ## Preview missing debt issues to create (no write)
	python3 scripts/debt_sync.py create-issues --limit 20

backup-db: ## Create a logical PostgreSQL backup (set NIC_POSTGRES_URL)
	@test -n "$(NIC_POSTGRES_URL)" || (echo "NIC_POSTGRES_URL is required"; exit 1)
	@mkdir -p backups
	@backup_file="backups/nic_$$(date +%Y%m%d_%H%M%S).sql"; \
	pg_dump --no-owner --no-privileges --format=plain --file="$$backup_file" "$(NIC_POSTGRES_URL)" && \
	echo "Backup created: $$backup_file"

restore-db: ## Restore a logical backup (set NIC_POSTGRES_URL and BACKUP_FILE=path.sql)
	@test -n "$(NIC_POSTGRES_URL)" || (echo "NIC_POSTGRES_URL is required"; exit 1)
	@test -n "$(BACKUP_FILE)" || (echo "BACKUP_FILE is required, e.g. make restore-db BACKUP_FILE=backups/nic_20260216_120000.sql"; exit 1)
	@psql "$(NIC_POSTGRES_URL)" -v ON_ERROR_STOP=1 -f "$(BACKUP_FILE)"
