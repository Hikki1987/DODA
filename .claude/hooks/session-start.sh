#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# Why this exists: the remote container has no systemd and gets recycled,
# so Postgres and Redis are simply not running when a session starts —
# even though their data directories survived. That matters more here than
# in most repos, because this project's house rule (CLAUDE.md, QOIDA 1:
# "DEMO != PRODUCTION") is that nothing counts as verified unless it ran
# against real Postgres(+Redis). Without this hook every session opens with
# a dead database and either 130+ confusing skips or a hand-restart dance.
#
# Deliberately synchronous: a session that starts before Postgres is up
# would just rediscover that same problem, which is the thing being fixed.
set -euo pipefail

# Local dev machines run their own services (README: `docker compose up -d`)
# and must not be touched by this.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$PROJECT_DIR"

log() { echo "[session-start] $*"; }

# --- Postgres ---------------------------------------------------------------
if ! pg_isready -q -h localhost -p 5432; then
  log "Postgres is not running — starting cluster 16/main"
  # A recycled container leaves a stale pid file behind; pg_ctlcluster
  # clears it itself, and "already running" must not fail the hook.
  pg_ctlcluster 16 main start || true
fi
for _ in $(seq 1 30); do
  pg_isready -q -h localhost -p 5432 && break
  sleep 1
done
pg_isready -h localhost -p 5432

# --- Redis ------------------------------------------------------------------
if ! redis-cli ping >/dev/null 2>&1; then
  log "Redis is not running — starting it"
  redis-server --daemonize yes --port 6379
  for _ in $(seq 1 15); do
    redis-cli ping >/dev/null 2>&1 && break
    sleep 1
  done
fi
redis-cli ping >/dev/null

# --- Database bootstrap (only if this cluster has never been provisioned) ---
# `doda` is deliberately NOT a superuser: ADR-005 makes RLS the second,
# independent tenant-isolation layer, and a superuser bypasses FORCE ROW
# LEVEL SECURITY no matter what the tables say (that exact mistake is
# written up in CLAUDE.md). Extensions therefore get created by `postgres`
# up front, since CREATE EXTENSION is the one step that needs superuser.
if ! su postgres -c "psql -tAc \"select 1 from pg_roles where rolname='doda'\"" | grep -q 1; then
  log "bootstrapping the 'doda' role"
  su postgres -c "psql -q -c \"create role doda login password 'doda' createdb nosuperuser\""
fi
if ! su postgres -c "psql -tAc \"select 1 from pg_database where datname='doda'\"" | grep -q 1; then
  log "bootstrapping the 'doda' database"
  su postgres -c "psql -q -c 'create database doda owner doda'"
fi
su postgres -c "psql -q -d doda -c 'create extension if not exists vector'"
su postgres -c "psql -q -d doda -c 'create extension if not exists pgcrypto'"

# --- Backend dependencies ---------------------------------------------------
cd "$PROJECT_DIR/backend"
if [ ! -x .venv/bin/python ]; then
  log "creating backend virtualenv"
  python3 -m venv .venv
fi
log "installing backend dependencies"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[dev]"

# --- Schema + least-privilege app role --------------------------------------
# Order matters and mirrors CI: migrations first (they create the tables),
# then the role script, which grants that role rights on what now exists.
log "applying migrations"
.venv/bin/alembic upgrade head
log "ensuring the least-privilege doda_app role and its grants"
PGPASSWORD=doda psql -q -h localhost -U doda -d doda -f ../infra/postgres-init/01-create-app-role.sql

# --- Frontend dependencies --------------------------------------------------
cd "$PROJECT_DIR/frontend"
log "installing frontend dependencies"
npm install --silent --no-fund --no-audit

# Put the backend venv first on PATH for the session, so pytest/ruff/mypy/
# alembic resolve without activating it by hand in every command.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$PROJECT_DIR/backend/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

log "ready: Postgres + Redis up, schema at head, deps installed"
