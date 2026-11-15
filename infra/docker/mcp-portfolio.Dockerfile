# syntax=docker/dockerfile:1.7
# Portfolio MCP server (Streamable HTTP on :8202). Retrieval runs here, so the embedding model is baked in;
# with QDRANT_URL set the vectors live in the Qdrant service.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH GIGBID_MODEL_CACHE=/opt/models
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"
COPY agent agent
COPY rag rag
COPY mcp_servers mcp_servers
COPY data/personas data/personas
COPY gigsim/seed/skill_hints.json gigsim/seed/skill_hints.json
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data/users /app/data/processed && chown -R app:app /app/data /opt/models
USER app
EXPOSE 8202
CMD ["python", "-m", "mcp_servers.portfolio.server", "--port", "8202"]
