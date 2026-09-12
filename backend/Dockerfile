# Production image for the backend — API server, and (via CMD override in
# docker-compose.prod.yml) the outbox/telegram relay workers, which are
# separate long-running processes from the same codebase (see
# infrastructure/outbox_relay.py, infrastructure/telegram_relay.py).
#
# Previously this project had no Dockerfile at all (README always pointed
# at running `uvicorn` directly on bare metal) — this is the first time
# any of it runs inside a container.
FROM python:3.12-slim AS base

# ADR-005's unprivileged-role discipline has a container-level analogue:
# the process inside this image should not run as root either.
RUN groupadd --system doda && useradd --system --gid doda --create-home doda

WORKDIR /app

# setuptools' package discovery (pyproject.toml: where = ["src"]) needs
# the source tree present at install time, so — unlike a plain
# requirements.txt image — dependencies and source can't be cached as two
# truly independent layers here. Copying the whole project before the one
# `pip install` is the correct-but-simpler trade: still skips bind-mounting
# node_modules-style bulk, just not a separate dependency-only cache layer.
COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY scripts ./scripts
COPY docker-entrypoint.sh ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN chmod +x docker-entrypoint.sh && chown -R doda:doda /app
USER doda

EXPOSE 8000

CMD ["uvicorn", "doda.main:app", "--host", "0.0.0.0", "--port", "8000"]
