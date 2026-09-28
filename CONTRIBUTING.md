# Contributing to PIC

Thank you for your interest in contributing to PIC (Product Image Clustering).

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker and Docker Compose

## Development Setup

The quickest way to see the whole app is `docker compose up --build -d` and http://localhost:8000/ui (see the README). For day-to-day work, run the database in Docker and the API and worker natively:

```bash
# Clone and install (the ml extra is needed for the worker and most tests)
git clone https://github.com/masa-57/PIC.git
cd PIC
uv sync --extra ml

# Environment: the defaults point at the Compose database and local storage in ./data
cp .env.example .env

# PostgreSQL with pgvector, then the schema
docker compose up -d db
uv run alembic upgrade head

# API with reload (JSON API at /api/v1, web UI at /ui, docs at /docs)
uv run fastapi dev src/pic/main.py

# In a second terminal: the worker that runs pipeline and clustering jobs
uv run pic-worker
```

Without `pic-worker`, jobs you start stay `pending`. Don't run it alongside the Compose `worker` service; start Compose with `docker compose up -d db` (or `db api`) instead.

The web UI is server-rendered (Jinja2 templates in `src/pic/ui/templates/`, vendored htmx, no build step), so template and CSS changes show on reload.

## Code Style

This project uses:
- **[ruff](https://docs.astral.sh/ruff/)** for linting and formatting
- **[mypy](https://mypy-lang.org/)** for type checking

All checks are enforced in CI.

```bash
# Lint
uv run ruff check src/ tests/ scripts/

# Format
uv run ruff format src/ tests/ scripts/

# Type check
uv run mypy src/pic/
```

## Running Tests

```bash
# Unit tests (fast, no external dependencies)
uv run pytest -m unit -v

# Integration tests: need PostgreSQL and TRUNCATE every table, so use a separate database
docker compose exec db psql -U pic -d pic -c "CREATE DATABASE pic_test"   # once
PIC_DATABASE_URL='postgresql+asyncpg://pic:pic_local@localhost:5432/pic_test?sslmode=disable' uv run pytest -m integration -v

# E2E tests (health checks against a running API)
PIC_E2E_BASE_URL=http://localhost:8000 uv run pytest -m e2e -v
```

Test markers:
- `unit` -- Fast tests with mocked dependencies
- `integration` -- Real PostgreSQL with pgvector
- `e2e` -- Checks against a running API instance

## Before Submitting a PR

Run these checks locally:

```bash
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run mypy src/pic/
uv run pytest -m unit -v
uv run pip-audit --skip-editable
uv lock --check
```

All must pass; CI runs the same checks plus the integration tests. `pre-commit install` sets up hooks that run ruff and mypy on commit and the unit tests on push.

## Pull Request Process

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes with tests
4. Ensure all checks pass (see above)
5. Submit a pull request with a clear description

## Reporting Issues

Use [GitHub Issues](https://github.com/masa-57/pic/issues) for bug reports and feature requests. For security vulnerabilities, see [SECURITY.md](SECURITY.md).

## Suggesting Features

Check [ROADMAP.md](ROADMAP.md) first -- items listed there are already planned and contributions are welcome. For new ideas, open a GitHub Issue using the Feature Request template.

## AI Coding Assistants

An `AGENTS.md` file provides structured context for AI coding assistants (Claude Code, Cursor, etc.). Human contributors can ignore it -- everything there is also covered in this guide and the README.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold this code.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
