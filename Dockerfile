# PIC images: `worker` (local job runner with ML deps) and `api` (slim, no ML deps).
# `api` is the LAST stage on purpose: platforms that build without a target get the API image.
# On Linux the lockfile resolves CPU-only torch, so the worker image has no CUDA.

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN adduser --disabled-password --gecos '' --uid 1001 appuser
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS worker
RUN uv sync --frozen --no-dev --extra ml --no-install-project
COPY README.md ./
COPY src/ src/
RUN uv sync --frozen --no-dev --extra ml
# DINOv2 weights download here on first run; compose mounts a volume so it happens once.
RUN mkdir -p /home/appuser/.cache/huggingface && chown -R appuser:appuser /home/appuser/.cache
USER appuser
CMD ["uv", "run", "--no-sync", "pic-worker"]

FROM base AS api
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md alembic.ini ./
COPY src/ src/
RUN uv sync --frozen --no-dev
USER appuser
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1
CMD uv run --no-sync fastapi run src/pic/main.py --host 0.0.0.0 --port $PORT
