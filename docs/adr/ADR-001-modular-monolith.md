# ADR-001: Modular monolith + separate worker, not microservices

**Status:** Accepted (TRD 6.4)

## Context

DODA is built by a single AI coding agent with one Product Owner (see
CLAUDE.md) — there is no multi-team organizational pressure toward
independently deployable services, and a microservice split would add
network boundaries, distributed transactions, and per-service operational
overhead that this project has no team to carry. At the same time, the
domain is genuinely multi-part (Identity, Customer/Workspace, Task, Action/
Approval, Audit, Notification, and eventually Knowledge/Chat), so an
undifferentiated single-file application would become unmaintainable.

## Decision

Build one deployable application, layered per TRD 6: Experience →
Application → Domain → AI → Integration → Data → Operations, with each
business area (`identity`, `customer`, `workspace`, `task`, `action`,
`audit`, `notification`, ...) as its own domain module under
`backend/src/doda/domain/`. A domain module never imports another domain
module's implementation directly — only an ID/reference column (e.g.
`customer_id: uuid.UUID`) or an application-layer port. This is enforced
mechanically, not just by convention: `tests/test_domain_isolation.py`
statically walks the AST of every domain module and fails if one imports
another's internals.

External side-effect delivery (the outbox relay, ADR-003) runs as a
separate worker process from the API, per TRD 6.3's "Redis + worker
abstraksiyasi" — this is the one process boundary that does exist, because
polling and request-serving have genuinely different runtime shapes, not
because of a service-ownership split.

## Consequences

**Positive**
- Single deploy unit, single database, no distributed transactions needed
  for the outbox/idempotency/approval chain that already works today.
- Cheap for one agent + one Product Owner to reason about and change.
- Domain boundaries are still real (mechanically checked), so a future
  extraction into services — if ever needed — has a natural seam.

**Negative**
- No network-level enforcement of domain boundaries; the AST check can be
  defeated by anyone willing to ignore CI red, unlike a real service
  boundary.
- Cannot scale one hot subdomain (e.g. a future high-volume connector)
  independently of the rest of the application without a real extraction
  effort later.
