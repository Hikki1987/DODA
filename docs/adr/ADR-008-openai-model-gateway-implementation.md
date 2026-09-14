# ADR-008: Model gateway implementation — OpenAI as the default provider

**Status:** Accepted — implemented.

## Context

ADR-004 recorded the decision to put all AI/model calls behind one
internal "model gateway" abstraction, but explicitly shipped no code —
"grep for `ModelGateway` returns nothing" was true at the time. Product
Owner requested a real integration, starting with OpenAI (the chosen
system-wide default provider), with the explicit constraints: verify the
actual current API/SDK/model names from primary sources rather than
training-data memory; never request or embed an API key in chat/code/
logs; build retry/timeout/budget controls with concurrency safety; and
keep the interface provider-swappable so a second/third provider is an
additive adapter, not a rewrite.

## Decision

`doda.ai.port.ModelGateway` (a `typing.Protocol`) is the one seam:
`stream_chat(*, model, mode, instructions, history, tools,
max_output_tokens, response_schema=None) -> AsyncIterator[GatewayEvent]`.
Every type it touches (`doda.ai.types`: `ChatTurn`, `ToolSpec`,
`ToolCallRequest`, `GatewayUsage`, and the `GatewayEvent` tagged union —
`TextDelta`/`ToolCallReady`/`StructuredOutputReady`/`Completed`/
`GatewayErrorEvent`) is provider-neutral; no OpenAI-shaped object ever
crosses into `doda.application.conversation_service`.

`doda.infrastructure.openai_gateway.OpenAIGateway` is the first real
adapter — the only module allowed to import the `openai` SDK (enforced by
`tests/unit/test_side_effect_boundary.py`'s AST layering check, the same
mechanism that already protected `telegram_client.py`). It uses OpenAI's
**Responses API** (`client.responses.create(stream=True, ...)`), not
Chat Completions — OpenAI's own SDK migration guidance recommends
Responses API for new integrations as of the version verified below.
`store=False` is always passed; this is distinct from OpenAI's separate
Zero Data Retention enrollment (an account-level setting, not a per-call
parameter — the SDK's own docstring makes this distinction, so
`store=False` is a privacy-minimizing default, not a claim that ZDR is
active).

Typed, provider-neutral errors (`doda.ai.errors`: `ModelNotConfiguredError`,
`ModelTimeoutError`, `ModelRateLimitedError`, `ModelProviderError`,
`ModelAuthenticationError`) are the only thing an adapter may raise — never
a raw SDK exception. Every error path extracts only structured, safe
fields (`type(exc).__name__`, `.status_code`, a provider-reported
`.message`) and never calls `str(exc)` on the raw SDK exception or logs
the request object, because the API key can appear in either (proven by a
dedicated test asserting a fake key never appears in a raised error's
`str()`/`repr()` — same discipline as `telegram_client.TelegramSendError`).

Budget enforcement (`doda.application.ai_budget_service`) is a two-phase
reserve/reconcile against a per-customer-per-month ledger
(`AIBudgetLedger`), locked with `SELECT ... FOR UPDATE` before every
read-modify-write — the same proven concurrency-safe pattern already used
for `audit_chain_tips`, task-status/approval-consume transitions, and the
last-owner invariant elsewhere in this codebase (see CLAUDE.md). The
reservation is sized for the WORST CASE of a full multi-round tool-calling
turn (`per_round_estimate × ai_max_tool_rounds`) and reconciled once per
turn against real usage — including on an unexpected failure
(`conversation_service.stream_message`'s `except Exception:` clause),
so a crash never leaves a phantom reservation that silently eats a
customer's future budget headroom.

**Primary-source verification (2026-09-12)**, via a fresh `pip install` of
each package into a throwaway virtualenv rather than training-data
memory: `openai` 3.13.0 — Responses API confirmed via
`openai.resources.responses`, streaming event types via
`openai.types.responses.response_stream_event`. Model ids
(`gpt-5-mini`, `gpt-5-nano`, `gpt-4.1-mini`) are primary-sourced from
`openai.types.shared.chat_model.ChatModel`'s own literal values in that
installed package. Pricing figures in
`doda.infrastructure.ai_pricing.MODEL_PRICING` are **not** primary-sourced
— every provider's own pricing page is blocked by this environment's
network egress policy (verified via `curl`: `platform.openai.com`,
`docs.anthropic.com`, `ai.google.dev` all return a proxy-level connect
rejection) — they are a multi-source web-search consensus, explicitly
flagged in that module's own docstring as "a reasoned starting point for
budget estimation, not contractually exact."

## Consequences

**Positive**
- `conversation_service.py` and the API layer never import `openai` —
  swapping the default provider, or adding a second one, never touches
  either (proven directly: the Gemini/Claude adapters added afterward,
  see ADR-009, required zero changes to `doda.ai.types`/`doda.ai.port`).
- Budget enforcement and tool-call routing (read tools execute
  immediately; write tools always go through the existing Action/Approval
  chain, never inline) are provider-independent by construction — built
  once against the Protocol, not per adapter.

**Negative / honest limitations**
- This environment's network egress policy blocks `api.openai.com` (same
  class of restriction already documented for Telegram/Google OAuth/
  Render elsewhere in this codebase) — no real end-to-end OpenAI call has
  ever been made or verified from this session. `OpenAIGateway` is
  verified only via `tests/unit/test_openai_gateway.py`, which exercises
  the SDK's own real parsing/streaming code against an `httpx2.
  MockTransport` double, not a live API. Do not report this as "tested
  against the real OpenAI API" — it has not been.
- Pricing figures are a starting estimate (see above), not verified
  against OpenAI's own billing dashboard — real spend should be
  reconciled against OpenAI's own usage reporting once a real key and
  real traffic exist.
- `doda.ai.capabilities`'s registry exists and is wired into
  `conversation_service.stream_message` (`assert_supports_tools`), but
  every provider this codebase configures supports tool calling today, so
  that check has never actually fired outside its own unit test's
  monkeypatched case.

## Status note

Implemented and tested (mock-transport only, see above) as of this ADR.
Superseded in scope, not replaced, by ADR-009 (Gemini + Claude adapters) —
`doda.ai.types`/`doda.ai.port` were designed generically enough here that
ADR-009 required no changes to either.
