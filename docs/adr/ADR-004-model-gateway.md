# ADR-004: Model gateway for AI provider abstraction

**Status:** Accepted (TRD 6.4) — **not yet implemented**

## Context

TRD 7.1: DODA must not be locked into a single AI model provider — pricing,
availability, and jurisdiction/legal risk (13-bo'lim, data residency) can
all change independently of DODA's own roadmap. Different call shapes
(reasoning, fast classification, embeddings, vision, speech) may also
reasonably use different providers or models even within a single logical
request.

## Decision

All AI/model calls will go through one internal "model gateway"
abstraction — the only module in the codebase allowed to know about a
specific provider's SDK or API shape. Every gateway call must record, in
telemetry, the provider, model, prompt version, token cost, latency, and
safety outcome — but never the raw prompt or completion content, matching
the same "no secrets/PII/prompt content in logs or audit" rule already
enforced for `AuditEvent` (FR-AUD-003, `domain/audit/models.py`) and for
the credential broker (9.3).

Per the Master Instruction (CLAUDE.md, "Model authoritative emas"): the
gateway's job is only to call a model and report what happened — it must
never be the thing that decides whether an action is authorized. That
decision stays in `authz_service`/`kill_switch_service`, entirely outside
this gateway.

## Consequences

**Positive**
- Swapping or adding a provider later touches one module, not every call
  site — supports NFR-PORT-001 ("provider-neutral domain va AI gateway").
- A single place to enforce "never log prompt content" and cost/latency
  telemetry, rather than re-implementing that discipline at every call
  site.

**Negative**
- The interface is speculative: no Chat or Knowledge domain exists yet in
  this codebase, so this gateway has never been exercised against a real
  caller. When stage 2 (Knowledge) or the chat domain is actually built,
  expect this shape to be revised — a follow-up ADR superseding this one
  is the right way to record that, not silently drifting from what's
  written here.

## Status note

This ADR records a decision, not a delivered feature. There is no AI/model
integration code anywhere in this codebase as of this ADR — grep for
`ModelGateway` or `model_gateway` returns nothing. Do not assume this
abstraction exists when planning stage 2/6 work; it has to be built.
