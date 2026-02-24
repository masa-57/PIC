# Contributing to PIC

Thank you for your interest in contributing to PIC (Product Image Clustering).

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker and Docker Compose
- PostgreSQL with [pgvector](https://github.com/pgvector/pgvector) extension (or use the provided Docker Compose)

## Development Setup

```bash
# Clone and install
git clone https://github.com/masa-57/pic.git
cd pic
uv sync --extra ml

# Start PostgreSQL with pgvector
docker compose up db -d

# Apply database migrations
uv run alembic upgrade head

# Copy and configure environment
cp .env.example .env
# Edit .env with your settings (at minimum: PIC_DATABASE_URL)

# Run the API server
uv run fastapi dev src/pic/main.py
```

The API will be available at `http://localhost:8000`. Interactive docs at `/docs`.

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

# Integration tests (requires Docker for PostgreSQL)
uv run pytest -m integration -v

# All tests
uv run pytest -v
```

Test markers:
- `unit` -- Fast tests with mocked dependencies
- `integration` -- Requires PostgreSQL with pgvector
- `e2e` -- Full pipeline tests (slow)

## Before Submitting a PR

Run these checks locally:

```bash
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run mypy src/pic/
uv run pytest -m unit -v
```

All four must pass.

## Pull Request Process

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes with tests
4. Ensure all checks pass (see above)
5. Submit a pull request with a clear description

## Reporting Issues

Use [GitHub Issues](https://github.com/masa-57/pic/issues) for bug reports and feature requests. For security vulnerabilities, see [SECURITY.md](SECURITY.md).

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold this code.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
