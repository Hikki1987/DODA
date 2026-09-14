# ADR-002: PostgreSQL + pgvector, not a separate vector database

**Status:** Accepted (TRD 6.4)

## Context

Knowledge/RAG (FR-KNW, stage 2 — not yet built) will need embedding storage
and similarity search. A dedicated vector database (Pinecone, Weaviate,
Qdrant, ...) is a common choice, but for a single-tenant-per-workspace,
single-operator project it means a second managed service: a second
credential to broker, a second backup/restore story (NFR-DUR-001), and —
critically for this project — a second place tenant isolation (NFR-ISO-001)
would have to be independently proven, on top of the PostgreSQL RLS layer
already built and hardened (ADR-005).

## Decision

Store embeddings in the same PostgreSQL database as everything else, using
the `pgvector` extension. The extension is already enabled in migration
`0001_foundation_schema.py` (`CREATE EXTENSION IF NOT EXISTS vector`), even
though no Knowledge domain or vector-bearing table exists yet — it was
turned on at foundation time so stage 2 doesn't need a database-level
change to begin.

## Consequences

**Positive**
- One database, one backup/PITR story, one RLS-based tenant-isolation
  model that automatically covers embedding rows the same way it covers
  every other tenant-scoped table — no second isolation mechanism to
  design or prove for vectors specifically.
- No new external credential/service for the connector broker (9.3) or
  audit trail to reason about.

**Negative**
- `pgvector`'s ANN indexing (ivfflat/hnsw) is less specialized than a
  purpose-built vector database at very large corpus sizes or very high
  query-per-second similarity search. If a single workspace's knowledge
  base grows far beyond what pgvector indexes comfortably, this decision
  should be revisited explicitly (a new ADR), not silently worked around.

## Status note

Accepted, but **not yet exercised** — the Knowledge/RAG domain (stage 2)
has not been built in this codebase as of this ADR. This decision governs
that future work; it has not yet been tested against a real embedding
workload.
