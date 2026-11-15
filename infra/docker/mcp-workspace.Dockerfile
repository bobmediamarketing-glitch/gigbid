# syntax=docker/dockerfile:1.7
# Workspace MCP server (Streamable HTTP on :8203): free slots, tentative holds, email drafts. Never sends.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY mcp_servers mcp_servers
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data/workspace /app/data/audit && chown -R app:app /app/data
USER app
ENV WORKSPACE_DIR=/app/data/workspace
EXPOSE 8203
CMD ["python", "-m", "mcp_servers.workspace.server", "--port", "8203"]
