# ADR-009: Multi-provider expansion — Google Gemini and Anthropic Claude

**Status:** Accepted — implemented.

## Context

Product Owner issued an explicit scope-expanding instruction canceling
ADR-008's original "OpenAI only, leave connection points for the rest"
boundary: DODA must support three real, user-selectable providers
(OpenAI, Google Gemini, Anthropic Claude) with OpenAI as the system-wide
default, behind one unified gateway, with provider-specific wire formats
strictly confined inside each adapter. The explicit requirements included
a deterministic 4-tier provider/model selection priority (conversation
pin > user default > workspace default > system default), safe
mid-conversation provider switching without leaking provider-specific
session/call ids across providers, and an opt-in (default OFF) automatic
fallback restricted to transient technical errors only — never bypassing
a security/budget/permission refusal.

## Decision

`doda.ai.types`/`doda.ai.port` (ADR-008) were designed generically enough
that this expansion required **zero changes to either file** — only new
adapters and a `Provider` enum value each already had. `doda.ai.factory.
get_gateway(provider, settings)` is the one place that picks an adapter
instance; no credential for a provider returns `NullModelGateway` for
THAT provider specifically — the explicit instruction that a user's
chosen provider failing must never be silently swapped for a different
one is enforced structurally here (proven in
`tests/unit/test_ai_factory.py`: configuring only OpenAI still returns
`NullModelGateway`, never `OpenAIGateway`, for Gemini/Claude).

### Two new adapters, each the only module allowed to import its own SDK

- `doda.infrastructure.gemini_gateway.GeminiGateway` — `google-genai`'s
  `client.aio.models.generate_content_stream(...)`. REST wire format uses
  camelCase keys (`usageMetadata`, `finishReason`, `functionCall`),
  auto-aliased to snake_case via `pydantic.ConfigDict(alias_generator=
  to_camel, populate_by_name=True)` inside the SDK itself — confirmed by
  direct source inspection, not assumed. `automatic_function_calling` is
  explicitly disabled in the request config, because the SDK can
  auto-invoke tool functions itself if given Python callables; this
  codebase always wants the call surfaced as a `ToolCallReady` event and
  routed through the existing Action/Approval chain, never executed by
  the SDK directly.
- `doda.infrastructure.claude_gateway.ClaudeGateway` — Anthropic's
  Messages API (`client.messages.create(stream=True, ...)`). Its
  streaming wire format is the one of the three that **requires** an
  explicit SSE `event:` line (confirmed by reading
  `anthropic/_streaming.py` directly) — OpenAI's discriminates purely on
  the JSON body's own `"type"` field. Native JSON-schema structured
  output has no equivalent in this SDK version (confirmed by the absence
  of any `response_format`-shaped parameter on `AsyncMessages.create`), so
  `response_schema` is emulated via a synthetic, forced single tool call
  whose input schema IS the requested schema
  (`_STRUCTURED_OUTPUT_TOOL_NAME`) — a real, working technique, but a
  provider-specific workaround rather than a native capability, which is
  exactly why `doda.ai.capabilities` exists as a registry rather than a
  call-site assumption.

Both adapters follow ADR-008's identical error-scrubbing discipline
(`type(exc).__name__`/`.status_code` only, never `str(exc)` on the raw SDK
exception) and are verified the same way: real SDK parsing/streaming code
exercised against a mock HTTP transport (`httpx.MockTransport` for
Gemini, since `google-genai` uses plain `httpx`; `httpx2.MockTransport`
for Claude, matching `anthropic`'s own transport dependency — `openai` and
`anthropic` both depend on `httpx2` 2.x, a separate major-version
successor package to `httpx`, for their transport layer).

### Provider/model selection and safe switching

`doda.application.ai_preference_service.resolve_provider_choice` resolves
provider AND model together per tier — never mixing a provider from one
tier with a model from another — in the exact order specified:
`Conversation.pinned_provider/pinned_model` (set only by
`conversation_service.switch_conversation_provider`) > `UserAIPreference`
> `WorkspaceAIPreference` > `Settings.ai_default_provider` +
`ai_model_{openai,gemini,claude}`. Setting one tier's preference never
rewrites another tier's stored row — pinning a conversation does not
change the user's or workspace's saved default, and vice versa (this is
enforced by construction: each tier is a separate table/column, never
copied into another).

History replay across a provider switch never carries a provider-specific
id across providers: `doda.domain.conversation.models.Message.
tool_call_id` stores whatever id the ORIGINATING provider assigned (or a
synthesized one, for response shapes that don't have one), and
`conversation_service._messages_to_history` reconstructs a fresh
`ToolCallRequest` from those stored columns on every replay — each
adapter then mints its OWN native call-id representation when building
that provider's request shape. No OpenAI response id, Gemini session
handle, or Claude message id is ever threaded into a different provider's
request.

### Capability gating, never a silent drop

`doda.ai.capabilities.capabilities_for(provider)` is a per-provider
registry (`ModelCapabilities`: `streaming`/`tool_calling`/
`structured_output`/`vision_input`), keyed by provider rather than
provider+model today — every model this codebase currently defaults to
shares one capability profile within its provider; a narrower, model-
specific override is added only once a real model that actually differs
is configured, not speculatively.
`conversation_service.stream_message` calls `assert_supports_tools`
before any gateway call, so an unsupported capability is refused with a
clear reason (`UnsupportedModelCapabilityError` → HTTP 422
`AI_CAPABILITY_UNSUPPORTED`) rather than the tool silently becoming
invisible to the model. All three providers configured today support
tool calling and structured output, so this has never actually fired
outside its own unit test's deliberately-monkeypatched case — it exists
for the first future model/provider that genuinely lacks one of these.

## Consequences

**Positive**
- Adding Gemini and Claude touched zero lines in `doda.ai.types`,
  `doda.ai.port`, `doda.application.conversation_service`'s orchestration
  loop, or the API layer — only new adapter modules and per-provider
  config/pricing table entries. This is the architecture ADR-008 promised
  actually holding up under its first real multi-provider test, not a
  speculative claim.
- A user's provider choice is never silently substituted — structurally
  true today (proven in tests), and the pattern (separate, explicit
  per-provider credential checks) extends cleanly to a fourth provider
  later.

**Negative / honest limitations**
- ~~The opt-in automatic fallback mechanism described in the original
  instruction is NOT YET BUILT.~~ **Built** (`doda.application.
  ai_provider_settings_service`, `CustomerAIFallbackSetting` — row
  absence means DISABLED, the opposite default from the provider-enabled
  table, deliberately, since silent automatic substitution must never be
  the unstated default). Restricted to exactly `ModelTimeoutError`/
  `ModelRateLimitedError`/`ModelProviderError` on round 0 with nothing yet
  produced this turn (no text, no tool call) — never
  `ModelAuthenticationError`/`ModelNotConfiguredError` (retrying
  elsewhere would only mask a real misconfiguration), and structurally
  unreachable for `BudgetExceededError`/`ProviderDisabledError`/
  `UnsupportedModelCapabilityError` (all raised before the round loop
  even starts). At most one fallback attempt per turn, in a fixed order
  (`FALLBACK_ORDER`), never a retry storm across all providers. Proven
  with scripted fake gateways in `tests/integration/
  test_conversations_api.py`: disabled-by-default leaves a transient
  failure as a normal error; enabled, the SAME failure completes
  silently on the substitute provider, and the conversation's own
  `pinned_provider` is untouched (the fallback never becomes a manual
  switch).
- ~~Per-provider admin settings (configured/tested/enabled/default,
  connection-test button) are NOT YET BUILT.~~ **Built**
  (`api/ai_settings.py`): `GET /v1/customers/{id}/ai-providers` (per-
  provider configured/enabled/last-verified status), `PUT .../ai-
  providers/{provider}/enabled` and `POST .../test-connection`
  (CustomerOwner-only), plus self-service `GET/PUT/DELETE .../me/ai-
  preference` and `GET/PUT/DELETE /v1/workspaces/{id}/ai-preference`
  (WorkspaceAdmin-only to write) — the set-default controls the original
  instruction asked for, which had no HTTP endpoint at all before this.
  "Test connection" makes one real, minimal call to the provider's own
  API (never trusts `NullModelGateway`'s always-succeeds reply as a
  substitute for an absent key) and records the result in a server-wide
  `AIProviderVerification` row — server-wide, not per customer, because
  the credential itself is a server-wide `Settings` value with no BYOK
  model.
- This environment's network egress policy blocks
  `generativelanguage.googleapis.com`/`api.anthropic.com` the same way it
  blocks `api.openai.com` (ADR-008) — no real end-to-end Gemini or Claude
  call has ever been made from this session. Both adapters are verified
  only via mock-transport tests exercising their real SDK's own parsing/
  streaming code, never a live API call.
- Pricing for `claude-sonnet-5`/`gemini-3.1-flash-lite` is the same
  honest-sourcing caveat as ADR-008's OpenAI figures: a multi-source
  web-search consensus, not a primary-source confirmation (see
  `doda.infrastructure.ai_pricing`'s own module docstring).
- Cost tracking today is broken out by provider/model/customer/
  workspace/conversation (`AIUsageEvent`), but NOT yet by "agent run" —
  there is no separate "agent run" concept in this codebase (a
  conversation turn is the closest equivalent), so that specific
  dimension from the original acceptance criteria is not represented as
  its own column.

## Status note

Implemented and tested (mock-transport only, see above) as of this ADR.
The fallback mechanism and provider settings API are tracked as
remaining, explicitly not-yet-started work — not silently dropped scope.
