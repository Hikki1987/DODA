# ADR-007: First connector choice

**Status:** Accepted — Telegram (Product Owner decision, OD-002 resolved; see
`docs/open-decisions.md`)

## Context

TRD 2.3 scopes v1 to "Bitta pilot konnektor (email yoki calendar)" — a
single external connector, deliberately not several at once (2.3's own
"SCOPE OGOHLANTIRISHI" warns against building many integrations in
parallel). Which one is a product choice (email vs. calendar vs.
Telegram vs. something else), and OD-002 names a hard deadline: "S5 oxiri"
(end of stage S5), blocking stage S6/S7 entirely if unresolved.

## Why this ADR exists without a decision

Same reasoning as ADR-006: this determines which OAuth/API surface the
credential broker (9.3) integrates with, what scopes get requested from a
real user, and what a real external side effect actually looks like for
the outbox relay (ADR-003) to finally prove end-to-end — none of which an
AI agent should pick on its own. It is recorded here so the decision point
itself isn't lost.

## Current state of the codebase relative to this decision

**The connector now exists.** `infrastructure/telegram_client.py` (Bot
API `sendMessage` client) and `infrastructure/telegram_relay.py` (the
Redis Stream consumer, scoped to `tool_name == telegram.send_message`,
driving `Action`s READY → RUNNING → SUCCEEDED/FAILED through the
existing `apply_transition` chokepoint) are built and tested. This
closes `outbox_relay.py`'s own former "connector hali yo'q" note — see
its updated docstring, which now points at `telegram_relay.py` as the
first real consumer of its Redis Stream output.

Independently of which connector was chosen, the server-side
`tool_name → minimum risk_level` policy this ADR's own text demanded
(per CLAUDE.md's security-review finding — without it, `risk_level` on a
proposed `Action` was entirely caller-supplied, letting a member declare
a sensitive tool call as `R0` and skip approval/step-up entirely) is
also built — see the Status note below.

## Decision

**Telegram**, per Product Owner decision (OD-002, resolved). No specific
reason was recorded beyond the choice itself — Telegram is one of the
two options TRD 2.3 named for the single v1 pilot connector (email or
calendar; Telegram is the "boshqa" option 2.3 also allows for).

## Status note (post-decision)

- The `tool_name → minimum risk_level` policy this ADR's own text
  demanded *before* any connector lands now has a real target: a
  `telegram.send_message` tool name was registered in
  `domain/action/tool_policy.py` at a minimum of R3 (matching the
  existing `send_email` precedent already used throughout the test
  suite — sending an external message is a meaningful, hard-to-undo
  side effect). `propose_action` now clamps any caller-supplied
  `risk_level` up to this floor rather than trusting it outright — see
  CLAUDE.md for the full writeup and the regression test proving a
  member can no longer self-declare a registered tool as R0.
- **The connector itself is now built.** The Product Owner supplied a
  real Telegram bot token through an environment variable
  (`DODA_TELEGRAM_BOT_TOKEN`, `config.py`) — never pasted into chat or
  committed to the repository, per the Master Instruction's "Secret,
  token... log yoki auditga yozma" rule extended to source control
  generally. `infrastructure/telegram_client.py` is the Bot API
  `sendMessage` client (token stays out of every log/exception message —
  it lives in the URL path per Telegram's own API design, so every error
  path avoids `str()` on the underlying httpx exception).
  `infrastructure/telegram_relay.py` is the outbox relay's real
  transport for this one tool: it consumes `doda:outbox:action.ready.v1`
  via a Redis Streams consumer group and drives the matching `Action`
  through `apply_transition` (READY → RUNNING → SUCCEEDED/FAILED),
  reusing the existing locking/audit/notification chokepoint rather than
  building a parallel one. Two independent idempotency layers guard
  against stream redelivery (proven via revert-test-restore — see
  `telegram_relay.py`'s own docstring and
  `test_telegram_relay.py::test_redelivery_of_an_already_succeeded_action_does_not_resend`).
- **Not yet built**: the credential broker (9.3) — today the bot token
  is read directly from `Settings` by the connector process itself, not
  fetched as a short-lived token from a broker that keeps the domain
  layer from ever seeing a raw credential. This is a smaller gap than it
  was before this connector existed (there was no credential of any kind
  to broker previously), but it remains real: today's `telegram_bot_token`
  is a long-lived static secret, not a broker-issued short-lived one.
- **Not yet verified**: no real Telegram bot token or chat is reachable
  from this development/CI environment, so the actual HTTP call to
  Telegram's live API has never been exercised here — only the
  outbox → Redis Stream → consumer → DB state pipeline is proven against
  real Postgres+Redis, with the Telegram HTTP leg itself under test
  doubles (`httpx.MockTransport`). The Product Owner's own deployment,
  where the real token lives, has not yet had this connector's live
  behavior confirmed against Telegram's actual service.
