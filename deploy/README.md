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
   `doda-backend` service Render just created:
   `https://doda-backend.onrender.com/v1/auth/google/callback` (swap in
   the real service URL Render assigns if it differs from this guess —
   Render's dashboard shows the exact URL on the service's page).
5. Wait for both services to finish their first build (Render's
   dashboard shows live build logs) — the backend's build also runs
   `alembic upgrade head` before starting (see `render.yaml`'s
   `dockerCommand`), so the schema is ready the moment it's live.
6. Open `https://doda-frontend.onrender.com/login` and try "Google
   orqali kirish."

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
