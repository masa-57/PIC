# API Dockerfile for PIC
# Worker runs on Modal (serverless GPU) — no worker stage needed

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS api
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src/ src/
RUN uv sync --frozen --no-dev

RUN adduser --disabled-password --gecos '' --uid 1001 appuser
USER appuser

ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1
CMD uv run fastapi run src/pic/main.py --host 0.0.0.0 --port $PORT
