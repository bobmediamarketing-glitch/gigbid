# GigBid on Hugging Face Spaces (Docker SDK, free CPU tier: 2 vCPU / 16 GB).
# Paste this file as `Dockerfile` in a new Docker Space. It builds GigBid from the public GitHub repo and runs
# the whole product in one container: API + web app + in-process MCP servers + embedded GigSim.
# Space secrets to set: REVIEWER_EMAIL, REVIEWER_PASSWORD (optional: GROQ_API_KEY, JWT_SECRET, TOKEN_ENCRYPTION_KEY).

FROM node:22-slim AS src
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
ARG REPO=https://github.com/bobmediamarketing-glitch/gigbid.git
ARG REF=main
ARG CACHEBUST=1
RUN git clone --depth 1 --branch "$REF" "$REPO" /src
WORKDIR /src/apps/web
RUN npm ci --no-audit --no-fund && npm run build && rm -rf node_modules

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH GIGBID_MODEL_CACHE=/opt/models
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
COPY --from=src /src /app
WORKDIR /app
RUN uv sync --frozen --no-dev --no-install-project
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"
RUN useradd -m -u 1000 user && mkdir -p /data && chown -R user /app /data /opt/models
USER user
ENV PORT=7860 GIGBID_ENV=production GIGBID_ALLOW_SIGNUP=0 GIGBID_EMBED_GIGSIM=1 \
    GIGSIM_BASE_URL=http://127.0.0.1:7860/gigsim GIGSIM_ERROR_RATE=0.02 GIGBID_SYNC_INTERVAL_S=10 MCP_MODE=inprocess
EXPOSE 7860
CMD ["bash", "infra/deploy/hf-space/start.sh"]
