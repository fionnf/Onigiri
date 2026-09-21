# Builds one image that can run either the API or the worker.
# The web app is built in the first stage and served by the API.

FROM node:22-slim AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg reads the audio and frames out of shared videos.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, from a stub package, so a source change does not reinstall them.
COPY server/pyproject.toml ./server/pyproject.toml
COPY server/onigiri/__init__.py ./server/onigiri/__init__.py
RUN pip install --upgrade pip && pip install ./server

COPY server/ ./server/
RUN pip install --no-deps --force-reinstall ./server
COPY --from=web /web/dist ./web/dist
ENV WEB_DIST=/app/web/dist

RUN useradd --create-home --uid 10001 onigiri && chown -R onigiri /app
USER onigiri

ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://127.0.0.1:${PORT}/api/health || exit 1

WORKDIR /app/server
CMD ["sh", "-c", "alembic upgrade head && uvicorn onigiri.main:app --host 0.0.0.0 --port ${PORT}"]
