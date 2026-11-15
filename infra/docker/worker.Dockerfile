# syntax=docker/dockerfile:1.7
# GigBid worker (Arq on Redis): graph runs, scheduled scouting per saved search, marketplace sync.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH GIGBID_MODEL_CACHE=/opt/models
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data /opt/models && chown -R app:app /app/data /opt/models
USER app
CMD ["arq", "worker.tasks.WorkerSettings"]
