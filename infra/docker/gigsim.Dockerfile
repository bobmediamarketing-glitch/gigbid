# syntax=docker/dockerfile:1.7
# GigSim marketplace simulator (provided; run unmodified).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY gigsim gigsim
RUN useradd --create-home --uid 1000 app && mkdir -p /app/gigsim/state && chown -R app:app /app/gigsim/state
USER app
ENV GIGSIM_STATE_FILE=/app/gigsim/state/state.json
EXPOSE 8100
CMD ["uvicorn", "gigsim.app:app", "--host", "0.0.0.0", "--port", "8100"]
