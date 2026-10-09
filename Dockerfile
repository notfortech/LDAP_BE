# Single image: the API plus the engine package it depends on.
#
# Multi-stage so the runtime layer carries no build toolchain. The
# engine is a path dependency in this repository, so it is installed
# first and explicitly -- pip will not resolve it from an index.

FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependency manifests first, so a code change does not invalidate the
# dependency layer.
COPY engine/pyproject.toml ./engine/
COPY api/pyproject.toml ./api/
COPY engine/src ./engine/src
COPY api/src ./api/src

RUN pip install ./engine \
 && pip install "./api[postgres]"

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Installed packages live under site-packages, so the engine's
    # repository-relative path does not resolve here. Set it explicitly.
    APTUS_ENGINE_CONFIG_DIR=/srv/engine/config/v1.0.0

# Runs unprivileged. Nothing in this image needs root, and a container
# that does not need it should not have it.
RUN useradd --create-home --uid 10001 aptus

COPY --from=build /opt/venv /opt/venv

WORKDIR /srv
# Engine configuration is read at runtime, and migrations run as the
# release command, so both ship in the image.
COPY engine/config ./engine/config
COPY api/migrations ./api/migrations
COPY api/alembic.ini ./api/

USER aptus
EXPOSE 8080

# --factory because create_app() validates configuration and the
# row-level-security posture before returning. A misconfigured
# production deployment fails here rather than serving requests.
#
# Shell form so ${PORT} expands: platforms that assign a port (Render,
# Heroku, Cloud Run) inject it and expect the process to bind to it.
# 8080 is the fallback for platforms that do not, and matches EXPOSE.
# exec replaces the shell so uvicorn is PID 1 and receives SIGTERM,
# otherwise the platform's graceful shutdown becomes a hard kill.
CMD ["sh", "-c", "exec uvicorn aptus_api.main:create_app --factory \
     --host 0.0.0.0 --port ${PORT:-8080} \
     --proxy-headers --forwarded-allow-ips '*'"]
