# One image for the whole app: FastAPI serves the API and the built PWA from one origin.
# Build: docker build -t watchtiming .   Deploy: fly deploy --ha=false (see CLAUDE.md)

# --- frontend: pnpm build -> frontend/dist ---
FROM node:24-slim AS web
WORKDIR /src
# pnpm at the version pinned in package.json's packageManager.
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json frontend/
RUN pnpm install --frozen-lockfile
COPY frontend/ frontend/
RUN pnpm --filter frontend build

# --- runtime: Python + the backend, serving frontend/dist ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first (cached while only the code changes), exactly as locked, no dev group.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/README.md ./
COPY backend/watchtiming/ watchtiming/
RUN uv sync --locked --no-dev
COPY --from=web /src/frontend/dist/ static/

RUN useradd --uid 1000 --no-create-home app && mkdir /data
# WATCHTIMING_DB lives on the Fly volume mounted at /data. Never set WATCHTIMING_SAVE_UPLOADS
# here: the product stores no images.
ENV PATH="/app/.venv/bin:$PATH" \
    WATCHTIMING_DB=/data/watchtiming.sqlite \
    WATCHTIMING_STATIC_DIR=/app/static
EXPOSE 8080
# Fly mounts the volume owned by root: hand it to `app`, then drop root for the server.
# One worker: each extra one loads its own OpenCV and would need more memory.
CMD ["sh", "-c", "chown app:app /data && exec setpriv --reuid=app --regid=app --init-groups \
     uvicorn watchtiming.api:app --host 0.0.0.0 --port 8080 --workers 1 \
     --proxy-headers --forwarded-allow-ips '*'"]
