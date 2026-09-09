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

No connector exists yet. `infrastructure/outbox_relay.py` currently
delivers only to a Redis Stream — a real connector call is exactly what's
missing to prove the outbox pattern (ADR-003) end-to-end, per the
`outbox_relay.py` docstring's own "connector hali yo'q" note.

Also blocking on this decision, independently of which connector is
chosen: per CLAUDE.md's security-review finding, a server-side
`tool_name → minimum risk_level` policy must be designed and built
**before** any connector lands — right now `risk_level` on a proposed
`Action` is entirely caller-supplied, so without this policy layer a
member could declare a sensitive tool call as `R0` and skip
approval/step-up entirely. That policy can't be designed against a real
tool taxonomy until this ADR's connector is chosen.

## Decision

**Telegram**, per Product Owner decision (OD-002, resolved). No specific
reason was recorded beyond the choice itself — Telegram is one of the
two options TRD 2.3 named for the single v1 pilot connector (email or
calendar; Telegram is the "boshqa" option 2.3 also allows for).

## Status note (post-decision)

The connector choice being made does **not** mean the connector itself is
built. As of this decision:

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
- The actual Telegram Bot API client, the credential broker (9.3) that
  hands it a short-lived token without the domain layer ever seeing the
  raw bot token, and the outbox relay's real transport (today it only
  proves delivery to a Redis Stream, per ADR-003) are **still not
  built**. This requires a real Telegram bot token, which must come from
  the Product Owner through a secure secret-management channel (e.g. an
  environment variable / secrets manager entry) — never pasted into a
  chat prompt or committed to the repository, per the Master
  Instruction's "Secret, token... log yoki auditga yozma" rule extended
  to source control generally.
