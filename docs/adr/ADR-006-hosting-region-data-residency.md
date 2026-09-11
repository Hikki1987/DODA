# ADR-006: Hosting region and data residency

**Status:** Accepted — OD-005 resolved by explicit Product Owner delegation (see `docs/open-decisions.md`)

## Context

TRD 13.3 lays out three hosting architectures — fully local (O'zbekiston),
hybrid (data local, AI inference external), fully external — with a
stated MVP recommendation of the hybrid variant, strict redaction for
sensitive data classes (C3/C4), and C4 never leaving to an external
provider by default. But the TRD itself marks the *final* choice open
(13.3: "Yakuniy qaror OD-005 sifatida ochiq"), and OD-005 was due
"S2 boshlanishidan oldin" (before stage 2/S2 begins).

## Why this ADR exists without a decision

Recording an open decision as its own ADR — rather than letting it live
only as a row in a table — is deliberate: this is exactly the kind of
choice a single AI coding agent must not make unilaterally (it determines
real infrastructure, a real hosting bill, and real legal exposure under
O'zbekiston qonunchiligi, none of which are engineering trade-offs this
agent is positioned to decide). Recording it here means the gap survives
context resets and session boundaries instead of being re-discovered from
scratch each time.

## Current state of the codebase relative to this decision

Nothing in this codebase currently depends on a specific hosting region —
there is no deployed infrastructure yet (local dev + CI only), so this
decision being open has not caused a concrete defect. It *will* determine,
once made: which managed Postgres/object-storage provider is viable
(NFR-DUR-001, ASM-005), how the credential broker (9.3) and future
connector's tokens are stored (KMS/Vault region), and how the "sensitive
data classification" redaction layer (13.2, OD-003) is designed.

## Decision

Product Owner explicitly delegated this choice to Claude ("serverlarni
sen o'zing tanlab, yozib qo'ygin") rather than deciding a specific
vendor/region personally. Chosen: the **hybrid** architecture TRD 13.3
itself recommends as the MVP default — data (Postgres, object storage)
hosted locally/nearby, AI inference calls go to an external provider, but
never with raw PII/sensitive content (OD-003 governs exactly what may
cross that boundary). Initial concrete vendor: **Hetzner Cloud
(Germany)** — inexpensive, and its VPS model is a direct fit for this
project's existing `docker-compose.yml`-based deployment shape (no
Kubernetes, no managed-service lock-in).

**Explicit limit on this decision**: this is a personal-use (OD-001),
reversible, technical starting point — not legal advice. If the project
is ever resold to other users (OD-001's "resellable later" half), the
real O'zbekiston data-residency/legal requirements TRD 13.3 itself flags
must be checked with actual legal counsel before onboarding anyone else;
an AI coding agent choosing a vendor is not a substitute for that review,
and this ADR does not claim to be one.

**Update — domain confirmed, deployment shape written.** Product Owner
confirmed `natsecurity.uz` is a real, already-owned domain, with explicit
instruction to build the server infrastructure fresh rather than assume
anything pre-existing behind that domain ("serverni o'zing boshqadan
o'zingdan yaratgin"). `backend/Dockerfile`, `frontend/Dockerfile`,
`docker-compose.prod.yml`, and `deploy/Caddyfile` (automatic HTTPS via
Let's Encrypt, path-based routing to the backend/frontend under one
origin) now exist — still the same Hetzner-shaped, plain-VPS/Docker
Compose deployment this ADR already chose, just written as real
infrastructure-as-code rather than a paragraph.

**Honest limit, unchanged in kind**: this session's own network policy
blocks the Docker Hub registry (the same class of restriction that
already applied to Telegram's and Google's APIs), so none of this has
been built with a real `docker build`, let alone deployed to a real
host. `deploy/README.md` states exactly what still needs a human (or
credentials handed to this agent): provisioning an actual server
(Hetzner account + payment, or a Hetzner API token), and pointing
`natsecurity.uz`'s DNS at it — an AI agent cannot create a billing
account or a DNS record it has no credentials for. Local dev and CI
remain the only environments actually exercised.
