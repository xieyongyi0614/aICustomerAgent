# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend
WORKDIR /build/apps/frontend
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci
ARG VITE_API_MODE=real
ARG VITE_BASE=/
ENV VITE_API_MODE=$VITE_API_MODE VITE_BASE=$VITE_BASE
COPY apps/frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /srv/backend
COPY apps/backend/pyproject.toml apps/backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY apps/backend/alembic.ini .
COPY apps/backend/app app
COPY apps/backend/migrations migrations
COPY apps/backend/scripts scripts
COPY --from=frontend /build/apps/frontend/dist /srv/frontend/dist
ENV FRONTEND_DIST_DIR=/srv/frontend/dist CONSOLE_HOST=0.0.0.0
EXPOSE 8020
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"CONSOLE_PORT\",\"8020\")}/health')"
CMD ["/bin/sh", "-c", "uv run alembic upgrade head && uv run python scripts/serve_with_frontend.py ${CONSOLE_PORT:-8020}"]
