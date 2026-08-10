# syntax=docker/dockerfile:1
#
# Aleph container build.
#
# Two independent targets:
#   --target frontend-build  -> produces the static site in /app/dist
#   --target api             -> produces the FastAPI service (default target)
#
# The stages are deliberately NOT chained: the API is useful without the site
# (batch pipeline runs, schema serving) and the site is useful without the API
# (GitHub Pages serves it from static JSON). Chaining them would make either
# build fail when the other is broken.
#
# No secrets are baked in. Every credential arrives at runtime via the
# environment; VITE_* build args are compiled into public JS and must therefore
# only ever carry public values.

# ---------------------------------------------------------------------------
# Stage: frontend-build — Vite production bundle
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend-build

# VITE_BASE defaults to "/" for container-served deployments. GitHub Pages
# serves the site from a subpath and overrides this with "/Aleph/".
ARG VITE_BASE="/"
# Empty means "no live API": the frontend falls back to the bundled static JSON.
ARG VITE_ALEPH_API_URL=""
ENV VITE_BASE=${VITE_BASE} \
    VITE_ALEPH_API_URL=${VITE_ALEPH_API_URL} \
    NODE_ENV=development

WORKDIR /app

# Dependency layer first: manifests only, so source edits do not bust the cache.
# The glob picks up package-lock.json when it is committed (the normal case) and
# still resolves when it is not, in which case we fall back to a plain install.
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Source layer.
COPY frontend/ ./

# The methodology page renders the JSON Schemas that define the data contract,
# so they ship with the site rather than being fetched from GitHub at runtime.
COPY schemas/ /schemas/
RUN mkdir -p public/data/schemas && cp /schemas/*.json public/data/schemas/ 2>/dev/null || true

RUN npm run build

# GitHub Pages and most static hosts have no SPA rewrite rule. The app uses a
# hash router, but a hard 404 fallback keeps deep links from dead-ending.
RUN [ -f dist/404.html ] || cp dist/index.html dist/404.html


# ---------------------------------------------------------------------------
# Stage: api — FastAPI service
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ALEPH_DATA_DIR=/app/data \
    ALEPH_SCHEMA_DIR=/app/schemas \
    XDG_CACHE_HOME=/app/.cache

WORKDIR /app

# Unprivileged runtime identity, created before anything is written so the
# ownership of /app is settled in a single layer.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin aleph

# --- Dependency layer -------------------------------------------------------
# Install third-party dependencies from the manifest alone. A placeholder
# package satisfies setuptools' discovery so this layer is keyed only on
# pyproject.toml and survives every source change.
COPY pyproject.toml ./
RUN mkdir -p aleph \
 && : > aleph/__init__.py \
 && pip install --no-cache-dir ".[api]" \
 && pip uninstall -y aleph \
 && rm -rf aleph build ./*.egg-info

# --- Source layer -----------------------------------------------------------
COPY aleph/ ./aleph/
COPY api/ ./api/
COPY schemas/ ./schemas/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY alembic.ini ./alembic.ini

# Link the real source into site-packages without re-resolving dependencies.
RUN pip install --no-cache-dir --no-deps -e . \
 && mkdir -p /app/data /app/.cache \
 && chown -R aleph:aleph /app

USER aleph

EXPOSE 8000

# Liveness is defined by the service's own contract endpoint, not by "the port
# is open": a process that boots but cannot load its schemas is not healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn api.main:app --host 0.0.0.0 --port 8000"]
