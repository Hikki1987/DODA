# Production deployment

**Status: infrastructure-as-code only — nothing here has been deployed to
a real server yet, and the Docker build itself has not been run in this
session's environment** (its network policy blocks the Docker Hub
registry, the same class of restriction that already applied to
Telegram's and Google's APIs — see CLAUDE.md). Everything below is
written and reasoned through, not proven end-to-end against a live host.

## What this covers

- `backend/Dockerfile`, `frontend/Dockerfile` — production images (no
  Dockerfile existed anywhere in this repo before).
- `docker-compose.prod.yml` — postgres, redis (with `--appendonly yes`
  for durability), a one-shot `migrate` service, the API, both relay
  workers (`outbox-relay`, `telegram-relay`), the frontend, and Caddy as
  a reverse proxy with automatic HTTPS.
- `deploy/Caddyfile` — path-based routing under one domain (`/v1/*` and
  `/metrics` to the backend, everything else to the frontend), so the
  browser app and the API share one origin in production.
- `.env.prod.example` — the real-secrets template `docker-compose.prod.yml`
  reads via `env_file: .env.prod` (gitignored, per this project's
  standing "never expose secrets" rule).

## Free MVP deploy (Render.com) — do this first

This is the path for getting a real, publicly-reachable MVP online
*today*, with no payment method and no VPS yet — `docker-compose.prod.yml`
+ a real domain (below) is the upgrade path once a paid VPS exists.

`render.yaml` at the repo root is a Render "Blueprint" — written from
long-stable knowledge of Render's format, but **not verified against
Render's current schema**: this session's network policy blocks
render.com entirely (confirmed with `curl` and even Anthropic's own
WebFetch tool — this is a blanket policy, not Render-specific). If a
field name has drifted, Render's dashboard will say so clearly when you
apply the Blueprint, and the manual fallback below works regardless of
whether the Blueprint itself parses cleanly.

**Scope of this free tier**: Postgres + the API + the frontend. No
Redis, no outbox-relay, no telegram-relay — Render has no free Redis,
and nothing on the request path needs one (only the two relay worker
processes touch Redis; the API itself never does — see
`tests/unit/test_side_effect_boundary.py`'s own comment on exactly this).
Login, workspaces, tasks, audit, kill switch — everything except
actually sending a Telegram message — works with no Redis at all.

### First real attempt: `doda-backend` failed to deploy — diagnosed and fixed

The first Blueprint sync (commit `d231456`) created `doda-postgres` and
`doda-frontend` successfully but `doda-backend` failed. Without access
to Render's own logs (this session can't reach render.com at all — see
above), the most likely cause by far: Render's Postgres gives out a
plain `postgres://...`/`postgresql://...` connection string, but
SQLAlchemy's async engine needs the `+asyncpg` driver named explicitly
or it resolves to a sync driver that isn't installed — and `db.py`
builds that engine at **module import time**, so the app would crash
before it could even bind to a port or answer a health check, which
matches "failed deploy" exactly.

Fixed at the config layer (`Settings`, not a one-off dashboard edit):
a `field_validator` on `database_url`/`migration_database_url` rewrites
a bare `postgres(ql)://` to `postgresql+asyncpg://` automatically —
proven with a revert-test-restore cycle (`tests/test_config.py`). This
means whatever connection string any managed Postgres provider hands
out (Render, Railway, Supabase, ...) just works, with no per-provider
manual edit. Render's Blueprint auto-redeploys `doda-backend` on the
next push to this branch; **if it still fails after that, the actual
cause is something else — check Render's own build/deploy logs on the
`doda-backend` service page and share them** so this can be diagnosed
for real rather than guessed at twice.

**Related, unverified nuance worth knowing**: Render's managed Postgres
gives one role for everything (no local-dev-style `doda`/`doda_app`
split — `infra/postgres-init/01-create-app-role.sql` only runs via
`docker-entrypoint-initdb.d`, which a managed Postgres service doesn't
use). That role is not a Postgres superuser, and `FORCE ROW LEVEL
SECURITY` (already on every tenant-scoped table, per
`test_rls_coverage.py`) is specifically what makes RLS apply even to a
table's own owner — so tenant isolation should still hold. This has
**not** been verified against Render's actual Postgres the way
`test_app_connects_as_a_role_that_cannot_bypass_row_level_security`
verifies it locally/in CI (this session cannot reach Render to check),
so treat it as a reasoned expectation, not a confirmed fact, until
someone runs that same check against the real service.

### Steps

1. **Sign up at [render.com](https://render.com)** using your GitHub
   account (the same `Hikki1987` account this repo is under) — no card
   needed for the free plan.
2. In Render's dashboard: **New +** → **Blueprint** → select the `DODA`
   repo → the branch this PR is on. Render reads `render.yaml` and shows
   a preview of what it's about to create (one Postgres database, two
   web services) — click **Apply**.
3. Render will pause on two environment variables marked `sync: false`
   in `render.yaml` and ask you to fill them in yourself, **directly in
   Render's dashboard** — never send these values to me:
   - `DODA_GOOGLE_OAUTH_CLIENT_SECRET` — the value you already have.
   - `DODA_TELEGRAM_BOT_TOKEN` — optional; leave blank if you'd rather
     wait for Redis to exist before the Telegram connector can do
     anything useful anyway.
4. **Google Cloud Console** — add an Authorized redirect URI for the
   `doda-backend` service Render just created. Render assigned this
   Blueprint's services suffixed hostnames rather than the clean
   `doda-backend.onrender.com`/`doda-frontend.onrender.com` this file's
   `name:` fields ask for (a prior failed-deploy attempt still held the
   bare names when this Blueprint was recreated from scratch) — the
   actual live URL is `https://doda-backend-jv8e.onrender.com`, so the
   redirect URI to register is
   `https://doda-backend-jv8e.onrender.com/v1/auth/google/callback`.
   Always double-check against the service's own page in Render's
   dashboard, since a future from-scratch recreation could get the
   clean names back (or a different suffix).
5. Wait for both services to finish their first build (Render's
   dashboard shows live build logs) — the backend's build also runs
   `alembic upgrade head` before starting (see `render.yaml`'s
   `dockerCommand`), so the schema is ready the moment it's live.
6. Open `https://doda-frontend-joh4.onrender.com/login` and try "Google
   orqali kirish." (again, the real suffixed hostname — see step 4.)

### If the frontend calls the wrong backend URL

`NEXT_PUBLIC_API_BASE_URL` has to be a Docker **build** argument, not a
runtime one (`frontend/Dockerfile`'s own comment explains why — Next.js
inlines it at build time). Whether `render.yaml`'s `envVars` can set a
Docker build arg the same way it sets a runtime one is exactly the kind
of schema detail this file couldn't verify. If login redirects work but
the app then fails to reach the API (check the browser console for
failed requests to `localhost` or the wrong host): open the
`doda-frontend` service in Render's dashboard → **Environment** → look
for a distinct "Docker Build Args" section (separate from the regular
env vars) → add `NEXT_PUBLIC_API_BASE_URL` = the real backend URL there
→ trigger a manual redeploy.

### Upgrading from here

Once a real VPS exists (see below), migrating is: point DNS, fill in
`.env.prod`, run the `docker-compose.prod.yml` sequence, confirm it
works, then delete the Render services (or leave them as a free
staging environment — Render's free web services just sleep when idle,
costing nothing).

**Before that first real VPS deploy, a Google Console step is required**
(found while reviewing this deployment shape, not yet done): add
`https://natsecurity.uz/v1/auth/google/callback` — **with** the `/v1`
prefix — as an Authorized redirect URI on the OAuth 2.0 Client in Google
Cloud Console. `deploy/Caddyfile` only routes `/v1/*` to the backend
(everything else goes to the frontend, which has no `/auth/google/callback`
route), and `api/auth.py`'s router is mounted at `/v1/auth` — so a redirect
URI without `/v1` reaches the frontend and 404s instead of completing
login. Add it alongside whatever is already registered there rather than
replacing it — an unused extra URI is harmless. This is separate from
whatever redirect URI is (or isn't) registered for the live Render MVP's
own domain (`https://doda-backend-jv8e.onrender.com` — see the "Free MVP
deploy" section above for why this isn't the clean `doda-backend.onrender.com`
name) — check that one is present too if Google login on the Render
deploy hasn't been tried yet.

## What still needs a human (or credentials handed to this agent)

This agent cannot sign up for a hosting account or register a payment
method — that is a real-world identity/billing action, not an
engineering one. Concretely, someone needs to either:

1. **Provision a server** — ADR-006 already picked Hetzner Cloud as the
   default (cheap, plain VPS, fits this Docker Compose shape with no
   Kubernetes/managed-service lock-in), but any Ubuntu/Debian VPS with
   Docker installed works. Either create it and hand over its IP + SSH
   access, or provide a Hetzner API token so this agent can provision one
   directly via their API.
2. **Point DNS** — an `A` (and `AAAA` if the server has IPv6) record for
   `natsecurity.uz` (and/or a subdomain, if that's preferred over the
   apex) at the server's IP. Whoever controls that domain's DNS zone
   needs to add this record, or hand over DNS provider access.
3. **Fill in `.env.prod`** from `.env.prod.example` — the Postgres
   password and the Google OAuth client secret specifically (never send
   the completed file anywhere insecure; if handing it to this agent,
   the values only, the same way the Telegram token and OAuth
   credentials were provided earlier this session).

## Once a server + DNS exist

```bash
git clone <this repo> && cd DODA
cp .env.prod.example .env.prod   # then fill in real values

# --env-file matters here, not just env_file: in the compose file itself:
# docker compose's own ${DODA_DOMAIN}/${POSTGRES_PASSWORD} substitution
# (used for Caddy's domain and the Postgres bootstrap password) reads a
# file named plain ".env" by default — a *different* mechanism from the
# `env_file:` directive that injects variables into each container.
# Pointing --env-file at .env.prod makes both read the one real file
# instead of silently defaulting the compose-level substitutions to
# empty strings (verified: without this flag, `docker compose config`
# prints exactly that warning for both variables).
alias dc='docker compose --env-file .env.prod -f docker-compose.prod.yml'

dc build
dc up -d postgres redis
dc run --rm migrate
dc up -d
```

Caddy requests its Let's Encrypt certificate automatically on first
request to `$DODA_DOMAIN` over port 80/443 — both need to be open on the
server's firewall, and DNS needs to already resolve there for the ACME
challenge to succeed.

## Honest gaps this deployment shape does not close

- No automated backup of the `doda_postgres_data` volume — a real
  production deployment needs one (e.g. `pg_dump` on a schedule, shipped
  off-host) before it holds anything that matters. Not built here;
  flagged rather than silently assumed.
- No CI step builds or pushes these images yet — `docker-compose.prod.yml`
  builds from source on the server itself (`build: context: ./backend`),
  which is simple and correct but means a deploy is a `git pull` + rebuild
  on the box, not a pre-built image pull. Fine at this scale; revisit if
  deploy time or server resource usage becomes a problem.
- `infra/postgres-init/01-create-app-role.sql` still hardcodes
  `doda_app`'s password as the literal string `doda_app` — real
  deployments should change that literal (and the matching
  `DODA_DATABASE_URL` in `.env.prod`) rather than ship the same password
  used in every local dev environment.
