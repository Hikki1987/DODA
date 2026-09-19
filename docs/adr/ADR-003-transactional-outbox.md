# ADR-003: Transactional outbox mandatory for external side effects

**Status:** Accepted (TRD 6.4) — implemented and tested

## Context

An external side effect (sending an email, writing to a calendar, and
eventually any connector action — FR-ACT) cannot be allowed to drift from
the database transaction that decided to perform it. Calling the external
API *before* the deciding transaction commits risks performing the effect
for a transaction that then rolls back; calling it strictly *after* commit,
in the same request, risks the process crashing in between — the DB says
"done", but nothing was ever sent, with no record that it needs retrying.

## Decision

Every external side effect is written as a row in `outbox_messages` inside
the **same** database transaction as the domain change that decides to
perform it (see `domain/outbox/models.py`). A separate worker process
(`infrastructure/outbox_relay.py`) polls unpublished rows and hands each to
a transport — currently a Redis Stream (per TRD 6.3's "Redis + worker
abstraksiyasi"); a real connector's broker call is the transport once one
exists (stage 3/S7 — no connector is built yet, see CLAUDE.md's "Bilingan
cheklovlar"). No request-handling code path calls an external API directly.

This combines with idempotency keys (FR-ACT-004, `Action.idempotency_key`)
so that at-least-once delivery from the outbox becomes effectively-once
from the caller's perspective — a retried delivery finds the same action
row rather than performing the effect twice.

## Consequences

**Positive**
- The database transaction is the single source of truth for "did we
  decide to do this" — no distributed transaction or two-phase commit is
  needed to keep the decision and the delivery record consistent.
- Combined with idempotency, effectively-once delivery is achievable with
  only a local commit, not a saga.

**Negative**
- Adds latency between "decided" and "delivered" — the relay polls rather
  than delivering synchronously in the same request.
- Needs its own always-running process (the worker from ADR-001).
- `outbox_messages` is one of three tables *intentionally* exempted from
  `FORCE ROW LEVEL SECURITY` (the other two — `workspace_tenant_index` and
  `user_customer_index` — are RLS bootstrap tables, see ADR-005) — the
  relay is a platform-level process that must see pending messages across
  every tenant, so per-tenant RLS would block it from doing its job. This
  is a deliberate, documented exception verified by
  `tests/test_rls_coverage.py`'s `KNOWN_RLS_EXEMPT_TABLES`, not an
  isolation gap: `outbox_messages` rows still carry
  `customer_id`/`workspace_id`, and nothing reads them except the relay
  itself.

## Verification

`FR-ACT-008`'s acceptance criteria (idempotent, outbox-delivered) are
covered by the integration test suite against real Postgres + Redis; the
relay's Redis Stream delivery is proven, but — per the limitation already
recorded in CLAUDE.md — no real external connector exists yet to prove
end-to-end delivery all the way to a third party. That is stage S7's job,
and per CLAUDE.md's security-review finding, a server-side
`tool_name → minimum risk_level` policy must land **before** the first
connector, or a caller could self-declare a sensitive tool as R0 and skip
approval entirely.
