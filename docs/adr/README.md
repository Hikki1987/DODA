# Architecture Decision Records

Tracks the ADR list from TRD 6.4 ("Muhim arxitektura qarorlari"). Numbers
and one-line decisions come from the TRD itself — these documents add the
project-specific context, real evidence, and consequences that the TRD's
one-row-per-ADR table doesn't have room for.

| ADR | Decision | Status |
|-----|----------|--------|
| [ADR-001](ADR-001-modular-monolith.md) | Modular monolith + worker, not microservices | Accepted |
| [ADR-002](ADR-002-pgvector.md) | PostgreSQL + pgvector, not a separate vector database | Accepted (not yet exercised) |
| [ADR-003](ADR-003-transactional-outbox.md) | Transactional outbox mandatory for external side effects | Accepted, implemented |
| [ADR-004](ADR-004-model-gateway.md) | Model gateway for AI provider abstraction | Accepted (not yet implemented) |
| [ADR-005](ADR-005-rls-second-layer.md) | PostgreSQL RLS as tenant isolation's second, independent layer | Accepted, implemented — see the recorded incident |
| [ADR-006](ADR-006-hosting-region-data-residency.md) | Hosting region and data residency | Open — see `docs/open-decisions.md` (OD-005) |
| [ADR-007](ADR-007-first-connector.md) | First connector choice | Accepted — Telegram (OD-002 resolved), integration not yet built |

No ADR-008+ exists yet — a new architecturally-significant decision (e.g.
introducing a `platform_owner` role for R5 dual control, per the gap
already documented in CLAUDE.md and in `docs/open-decisions.md`'s OD-006
row) should get the next number, not overwrite one of these.
