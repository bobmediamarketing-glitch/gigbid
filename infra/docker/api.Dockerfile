# syntax=docker/dockerfile:1.7
# GigBid API. Also serves the built web app, so this one image can run the whole product on a single-container
# host (MCP_MODE=inprocess, no REDIS_URL). In docker compose it runs behind the `web` service with the worker,
# the MCP services and Postgres/Redis/Qdrant.

FROM node:22-slim AS webbuild
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH GIGBID_MODEL_CACHE=/opt/models
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Embedding model baked in (in-process mode retrieves locally; no download at runtime).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"
COPY . .
COPY --from=webbuild /web/dist apps/web/dist
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown -R app:app /app/data /opt/models
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ping').status==200 else 1)"
CMD ["sh", "-c", "uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
