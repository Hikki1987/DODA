"""Provider-neutral types for the AI layer (ADR-004/ADR-008, TRD 6.1/7.1).

Nothing here names OpenAI (or any other provider) — that is the whole
point of `doda.ai.port.ModelGateway`: an adapter (e.g.
`doda.infrastructure.openai_gateway`) translates provider-specific SDK
shapes into these types and back, so `application/conversation_service.py`
never sees an OpenAI-shaped object. Swapping providers later means writing
a new adapter against this same module, not touching the application
layer or the API routes.
"""

import dataclasses
import enum
from typing import Any

from doda.ai.errors import ModelGatewayError


class ChatMode(enum.StrEnum):
    """TRD's FAST/STANDARD/DEEP tiers. Selects a max-output/cost ceiling
    from config (`doda.config.Settings`) — orthogonal to `Provider`/model
    choice below. A DEEP request to any provider gets a higher output
    ceiling and its own per-request cost guard; FAST/STANDARD/DEEP is not
    itself a model selector once multiple providers exist."""

    FAST = "FAST"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class Provider(enum.StrEnum):
    """The three real adapters this codebase implements (ADR-008/ADR-009).
    `doda.config.Settings.ai_default_provider` is the system-wide fallback
    (OpenAI, Product Owner decision); `doda.application.ai_preference_
    service` resolves conversation/user/workspace overrides above it."""

    OPENAI = "OPENAI"
    GEMINI = "GEMINI"
    CLAUDE = "CLAUDE"


class ChatRole(enum.StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


@dataclasses.dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call. `parameters_schema` is a JSON Schema
    object (typically `SomePydanticModel.model_json_schema()`) — the
    adapter is responsible for translating this into whatever shape the
    provider's own tool-definition format wants."""

    name: str
    description: str
    parameters_schema: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class ToolCallRequest:
    """The model asking to call one of the tools it was offered.
    `call_id` is the provider's own identifier for this specific call —
    used to build a deterministic Action idempotency key
    (`doda.application.ai_tools`), so a retried gateway call that
    re-surfaces "the same" tool call never creates a second Action. When
    reconstructed from stored history (`doda.domain.conversation.models.
    Message`) for a DIFFERENT provider than the one that originally made
    the call, `call_id` is a freshly synthesized id, never the original
    provider's own id carried across — see `ChatTurn.tool_calls`."""

    call_id: str
    name: str
    arguments_json: str


@dataclasses.dataclass(frozen=True)
class ChatTurn:
    """One turn of conversation history handed to the gateway.

    - USER/ASSISTANT turns with no `tool_calls`: plain text, `content`.
    - An ASSISTANT turn that requested one or more tool calls sets
      `tool_calls` (`content` is usually empty) — each adapter
      reconstructs ITS OWN native representation of "the model called
      these tools" from this list (e.g. OpenAI's `function_call` input
      items, Gemini's `Part.from_function_call`, Claude's `tool_use`
      content blocks).
    - A TOOL turn is that call's result fed back: `tool_call_id` names
      which call (matching one entry in the preceding ASSISTANT turn's
      `tool_calls`), `content` is the result text.
    """

    role: ChatRole
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCallRequest] | None = None


@dataclasses.dataclass(frozen=True)
class GatewayUsage:
    """Token accounting for one gateway call — see
    `doda.application.ai_budget_service` for how this becomes a cost
    figure. Never includes prompt or completion content."""

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


# ---- Streaming events -------------------------------------------------
# A tagged union (one dataclass per event kind) rather than a single
# dataclass with optional fields — a caller pattern-matching on `type()`
# can't accidentally read a field that doesn't apply to the event it got.


@dataclasses.dataclass(frozen=True)
class TextDelta:
    """A chunk of assistant text to append to the message being streamed."""

    text: str


@dataclasses.dataclass(frozen=True)
class ToolCallReady:
    """The model has finished requesting one tool call, with complete
    (not partial) arguments. Unlike text, tool-call argument deltas are
    not surfaced to callers — `doda.application.ai_tools` needs the full,
    valid JSON to validate arguments, and a partial-JSON event would have
    no safe use on this side of the boundary."""

    call: ToolCallRequest


@dataclasses.dataclass(frozen=True)
class StructuredOutputReady:
    """The model's complete answer, already validated against the
    `response_schema` the caller requested (`ModelGateway.stream_chat`'s
    `response_schema` parameter) — emitted INSTEAD OF a final TextDelta
    when structured output was requested and the provider/model supports
    it (`doda.ai.capabilities`). Emitted once, with the full parsed
    object, never as partial/delta JSON — half a JSON document has no
    safe use on this side of the boundary, same reasoning as
    ToolCallReady."""

    data: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class Completed:
    """The gateway call finished normally. `finish_reason` is one of
    "stop" (model produced a final answer), "tool_calls" (one or more
    ToolCallReady events preceded this and the caller must dispatch them),
    or "length" (max_output_tokens was hit — FR-CONV-008: the caller must
    mark the message incomplete, never claim it as a full answer)."""

    usage: GatewayUsage
    finish_reason: str


@dataclasses.dataclass(frozen=True)
class GatewayErrorEvent:
    """A terminal error for this stream — the adapter has already decided
    this is not retryable (see `doda.ai.errors` for the retryable/not
    split); by the time this event reaches a caller, retrying is either
    already exhausted or was never appropriate."""

    error: ModelGatewayError


GatewayEvent = TextDelta | ToolCallReady | StructuredOutputReady | Completed | GatewayErrorEvent
