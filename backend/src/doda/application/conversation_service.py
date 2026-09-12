"""Conversation orchestration — FR-CONV, ADR-008/ADR-009. The one place
that ties together provider/model resolution, the budget ledger, the
tool registry, and the three gateways behind one provider-neutral loop.

Per-turn flow (`stream_message`):

1. Persist the user's Message immediately (before any provider call).
2. Resolve provider/model (`doda.application.ai_preference_service`).
3. Reserve a worst-case budget estimate for the WHOLE turn (covering up
   to `ai_max_tool_rounds` gateway calls) BEFORE any provider call —
   "bir vaqtning o'zida kelgan so'rovlar budjet cheklovini chetlab
   o'tmasin" means the check must happen first, not after.
4. Loop, up to `ai_max_tool_rounds` times: call the gateway with the
   current (provider-neutral) history; for each event, either stream
   text to the caller, or dispatch a tool call:
   - READ tools execute immediately and feed their result back in for
     another round.
   - WRITE tools never execute inline — they propose an Action through
     the existing approval chain and END the turn with a deterministic,
     non-model-generated status message (never a model-hallucinated
     "done").
5. Reconcile the budget with the real summed usage from however many
   rounds actually happened, and persist every turn (user/assistant/
   tool) as Message rows so the NEXT turn's history replay is accurate.

Nothing here decides authorization — `authorize_use_chat` already ran
before this is called, and every tool dispatch goes through its own
existing authz-aware path (`ai_tools.py`). This module's only "decision"
is whether the account can still afford the call (budget), which is not
an authorization decision about WHO may act.
"""

import dataclasses
import json
import typing
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.ai.capabilities import assert_supports_tools
from doda.ai.errors import ModelProviderError, ModelRateLimitedError, ModelTimeoutError
from doda.ai.factory import get_gateway
from doda.ai.types import (
    ChatMode,
    ChatRole,
    ChatTurn,
    Completed,
    GatewayUsage,
    Provider,
    StructuredOutputReady,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
)
from doda.application import ai_budget_service, ai_preference_service, ai_provider_settings_service
from doda.application.ai_preference_service import ResolvedProviderChoice, default_model_for
from doda.application.ai_tools import (
    available_tool_specs,
    dispatch_read_tool,
    is_read_tool,
    is_write_tool,
    propose_write_tool_action,
)
from doda.application.authz_service import WorkspaceContext
from doda.config import Settings
from doda.domain.conversation.models import Conversation, Message, MessageRole
from doda.infrastructure.ai_pricing import estimate_cost_cents, estimate_input_tokens_from_chars

MAX_PAGE_SIZE = 200

_MAX_OUTPUT_TOKENS_BY_MODE = {
    ChatMode.FAST: "ai_max_output_tokens_fast",
    ChatMode.STANDARD: "ai_max_output_tokens_standard",
    ChatMode.DEEP: "ai_max_output_tokens_deep",
}


class DeepRequestCostCeilingExceededError(Exception):
    """DEEP mode's own, separate per-request cost guard — distinct from
    the shared monthly BudgetExceededError."""


@dataclasses.dataclass(frozen=True)
class TurnChunk:
    """One streamed unit the API layer turns into an SSE event. A tagged
    union of the few things a caller watching one chat turn needs to
    know about — deliberately narrower than the full `GatewayEvent`
    union, since e.g. raw ToolCallReady/StructuredOutputReady are
    resolved internally before the caller ever sees this turn's output."""

    kind: str  # "text" | "tool_status" | "done" | "error"
    text: str = ""
    message: Message | None = None


async def start_conversation(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    workspace_id: uuid.UUID,
    owner_id: str,
    title: str | None = None,
) -> Conversation:
    conversation = Conversation(
        customer_id=customer_id, workspace_id=workspace_id, owner_id=owner_id, title=title
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def list_conversations_for_workspace(
    session: AsyncSession, *, workspace_id: uuid.UUID, limit: int = 50
) -> list[Conversation]:
    limit = min(limit, MAX_PAGE_SIZE)
    result = await session.execute(
        select(Conversation)
        .where(Conversation.workspace_id == workspace_id)
        .order_by(Conversation.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_messages(
    session: AsyncSession, *, conversation_id: uuid.UUID, limit: int = 200
) -> list[Message]:
    limit = min(limit, MAX_PAGE_SIZE)
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def switch_conversation_provider(
    session: AsyncSession, conversation: Conversation, *, provider: Provider, model: str | None
) -> Conversation:
    """Pins this ONE conversation to a provider/model going forward —
    never the user's or workspace's saved default (the instruction is
    symmetric: neither direction auto-propagates). Takes effect on the
    NEXT message only; nothing about messages already sent changes
    (`doda.domain.conversation.models.Message.provider/model` is set
    once, at write time, per message)."""
    conversation.pinned_provider = provider.value
    conversation.pinned_model = model
    await session.flush()
    return conversation


def _messages_to_history(messages: list[Message], *, max_chars: int) -> list[ChatTurn]:
    """ "tegishli va hajmi cheklangan kontekstni tanla" — most-recent
    messages first, up to a character budget, no summarization/retrieval
    (Knowledge/RAG doesn't exist to do either yet). Reconstructs tool-
    call turns from the stored tool_name/tool_arguments_json columns, not
    just plain text, so multi-turn tool use replays correctly."""
    selected: list[Message] = []
    total_chars = 0
    for message in reversed(messages):
        cost = len(message.content) + len(message.tool_arguments_json or "")
        if selected and total_chars + cost > max_chars:
            break
        selected.append(message)
        total_chars += cost
    selected.reverse()

    turns: list[ChatTurn] = []
    for message in selected:
        if message.role is MessageRole.TOOL:
            turns.append(
                ChatTurn(role=ChatRole.TOOL, content=message.content, tool_call_id=message.tool_call_id)
            )
        elif message.role is MessageRole.ASSISTANT and message.tool_name is not None:
            turns.append(
                ChatTurn(
                    role=ChatRole.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCallRequest(
                            call_id=message.tool_call_id or str(message.id),
                            name=message.tool_name,
                            arguments_json=message.tool_arguments_json or "{}",
                        )
                    ],
                )
            )
        else:
            role = ChatRole.USER if message.role is MessageRole.USER else ChatRole.ASSISTANT
            turns.append(ChatTurn(role=role, content=message.content))
    return turns


def _max_output_tokens(settings: Settings, mode: ChatMode) -> int:
    return int(getattr(settings, _MAX_OUTPUT_TOKENS_BY_MODE[mode]))


async def stream_message(
    session: AsyncSession,
    conversation: Conversation,
    *,
    workspace_context: WorkspaceContext,
    content: str,
    mode: ChatMode,
    trace_id: uuid.UUID,
    settings: Settings,
) -> typing.AsyncIterator[TurnChunk]:
    """An async generator of `TurnChunk`s — the API layer
    (`api/conversations.py`) turns each into an SSE event. Raises
    `BudgetExceededError`/`DeepRequestCostCeilingExceededError` BEFORE
    yielding anything and before any provider call, so a caller can
    translate those into a clean 4xx without any partial stream having
    started.
    """
    user_message = Message(
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content=content,
    )
    session.add(user_message)
    await session.flush()

    choice = await ai_preference_service.resolve_provider_choice(
        session,
        settings=settings,
        conversation=conversation,
        customer_id=workspace_context.customer_id,
        user_id=workspace_context.user_id,
        workspace_id=workspace_context.workspace_id,
    )
    # A CustomerOwner disabling a provider (ai_provider_settings_service)
    # must actually stop it from being used — checked right after
    # resolution, before any budget reservation or provider call, and
    # BEFORE falling back to anything: a disabled provider is refused,
    # never silently substituted for a different one (the explicit
    # instruction this whole module's docstring already states).
    await ai_provider_settings_service.assert_provider_enabled(
        session, customer_id=workspace_context.customer_id, provider=choice.provider
    )
    model = choice.model or ""
    max_output_tokens = _max_output_tokens(settings, mode)
    tools = available_tool_specs()
    # TRD 7.1 / the multi-provider instruction: an unsupported capability
    # must be refused with a clear reason, never silently dropped — e.g.
    # sending `tools` to a model that cannot call them would make every
    # tool invisible to the user with no explanation. Checked BEFORE any
    # budget reservation or provider call — every provider this codebase
    # configures supports tool calling today (doda.ai.capabilities' own
    # module docstring), so this never raises yet; it exists so a future
    # provider/model that genuinely lacks the capability is rejected
    # here, not discovered as a silent no-op.
    assert_supports_tools(choice.provider, requested_tools=[t.name for t in tools])

    history = _messages_to_history(
        await list_messages(session, conversation_id=conversation.id), max_chars=settings.ai_max_context_chars
    )
    estimated_input_tokens = estimate_input_tokens_from_chars(sum(len(t.content) for t in history))
    per_round_cost_cents = estimate_cost_cents(
        choice.provider, model, input_tokens=estimated_input_tokens, output_tokens=max_output_tokens
    )
    total_estimate_cents = per_round_cost_cents * settings.ai_max_tool_rounds

    if mode is ChatMode.DEEP:
        ceiling_cents = round(settings.ai_deep_request_cost_ceiling_usd * 100)
        if total_estimate_cents > ceiling_cents:
            raise DeepRequestCostCeilingExceededError(
                f"estimated cost ${total_estimate_cents / 100:.2f} exceeds the DEEP per-request ceiling "
                f"${settings.ai_deep_request_cost_ceiling_usd:.2f}"
            )

    await ai_budget_service.reserve_budget(
        session, customer_id=workspace_context.customer_id, estimated_cost_cents=total_estimate_cents
    )

    gateway = get_gateway(choice.provider, settings)
    total_usage = GatewayUsage(input_tokens=0, output_tokens=0)
    final_assistant_message: Message | None = None

    try:
        fallback_attempted = False
        while True:
            try:
                for _round_index in range(settings.ai_max_tool_rounds):
                    accumulated_text = ""
                    tool_calls_this_round: list[ToolCallRequest] = []
                    finish_reason = "stop"

                    async for event in gateway.stream_chat(
                        model=model,
                        mode=mode,
                        instructions="",
                        history=history,
                        tools=tools,
                        max_output_tokens=max_output_tokens,
                    ):
                        if isinstance(event, TextDelta):
                            accumulated_text += event.text
                            yield TurnChunk(kind="text", text=event.text)
                        elif isinstance(event, ToolCallReady):
                            tool_calls_this_round.append(event.call)
                        elif isinstance(event, StructuredOutputReady):
                            accumulated_text = json.dumps(event.data)
                        elif isinstance(event, Completed):
                            finish_reason = event.finish_reason
                            total_usage = GatewayUsage(
                                input_tokens=total_usage.input_tokens + event.usage.input_tokens,
                                output_tokens=total_usage.output_tokens + event.usage.output_tokens,
                                cached_input_tokens=total_usage.cached_input_tokens
                                + event.usage.cached_input_tokens,
                            )

                    if not tool_calls_this_round:
                        final_assistant_message = Message(
                            customer_id=conversation.customer_id,
                            conversation_id=conversation.id,
                            role=MessageRole.ASSISTANT,
                            content=accumulated_text,
                            provider=choice.provider.value,
                            model=model,
                            finish_reason=finish_reason,
                        )
                        session.add(final_assistant_message)
                        await session.flush()
                        break

                    # At least one tool call: persist the assistant's tool-call
                    # turn(s), then either dispatch (read) or stop (write).
                    write_calls = [c for c in tool_calls_this_round if is_write_tool(c.name)]
                    read_calls = [c for c in tool_calls_this_round if is_read_tool(c.name)]

                    for call in tool_calls_this_round:
                        assistant_tool_message = Message(
                            customer_id=conversation.customer_id,
                            conversation_id=conversation.id,
                            role=MessageRole.ASSISTANT,
                            content=accumulated_text,
                            tool_call_id=call.call_id,
                            tool_name=call.name,
                            tool_arguments_json=call.arguments_json,
                            provider=choice.provider.value,
                            model=model,
                            finish_reason="tool_calls",
                        )
                        session.add(assistant_tool_message)
                    await session.flush()
                    history.append(
                        ChatTurn(
                            role=ChatRole.ASSISTANT,
                            content=accumulated_text,
                            tool_calls=tool_calls_this_round,
                        )
                    )

                    if write_calls:
                        # Never execute inline, never let another model round
                        # pretend it happened — see module docstring.
                        call = write_calls[0]
                        idempotency_key = f"chat:{conversation.id}:{call.call_id}"
                        action, approval = await propose_write_tool_action(
                            session,
                            tool_name=call.name,
                            arguments_json=call.arguments_json,
                            workspace_context=workspace_context,
                            trace_id=trace_id,
                            idempotency_key=idempotency_key,
                        )
                        status_text = (
                            f"Men '{call.name}' vositasini taklif qildim — holati: {action.status.value}. "
                            "Bu amal inson tasdig'isiz bajarilmaydi."
                        )
                        final_assistant_message = Message(
                            customer_id=conversation.customer_id,
                            conversation_id=conversation.id,
                            role=MessageRole.ASSISTANT,
                            content=status_text,
                            provider=choice.provider.value,
                            model=model,
                            finish_reason="tool_calls",
                        )
                        session.add(final_assistant_message)
                        await session.flush()
                        yield TurnChunk(kind="tool_status", text=status_text)
                        break

                    for call in read_calls:
                        try:
                            result_text = await dispatch_read_tool(
                                session,
                                tool_name=call.name,
                                arguments_json=call.arguments_json,
                                workspace_id=workspace_context.workspace_id,
                            )
                        except Exception as exc:  # ToolArgumentsInvalidError/ToolNotFoundError
                            result_text = f"Tool error: {exc}"
                        tool_result_message = Message(
                            customer_id=conversation.customer_id,
                            conversation_id=conversation.id,
                            role=MessageRole.TOOL,
                            content=result_text,
                            tool_call_id=call.call_id,
                        )
                        session.add(tool_result_message)
                        history.append(
                            ChatTurn(role=ChatRole.TOOL, content=result_text, tool_call_id=call.call_id)
                        )
                    await session.flush()
                else:
                    # Exhausted ai_max_tool_rounds without a final text answer —
                    # FR-CONV-008: surface as incomplete, never a silent success.
                    final_assistant_message = Message(
                        customer_id=conversation.customer_id,
                        conversation_id=conversation.id,
                        role=MessageRole.ASSISTANT,
                        content="Juda ko'p vosita chaqiruvidan so'ng yakuniy javob topilmadi.",
                        provider=choice.provider.value,
                        model=model,
                        finish_reason="length",
                    )
                    session.add(final_assistant_message)
                    await session.flush()
                break
            except (ModelTimeoutError, ModelRateLimitedError, ModelProviderError):
                # Opt-in, default-OFF automatic fallback (doda.
                # application.ai_provider_settings_service) — restricted
                # to exactly these three TRANSIENT error types, never
                # ModelAuthenticationError/ModelNotConfiguredError (a
                # real misconfiguration retrying elsewhere would only
                # mask), and never BudgetExceededError/
                # ProviderDisabledError/UnsupportedModelCapabilityError
                # (already raised before this loop even starts, so they
                # can never reach here at all — a refusal is never
                # silently routed around). Only eligible on round 0 with
                # NOTHING yet produced this turn (no text, no tool call):
                # once any byte has reached the caller or any tool/Action
                # side effect has happened, swapping providers mid-turn
                # would mean either mixing two providers' text in one
                # answer or risking a duplicate side effect — neither of
                # which "fallback, never conflated with manual switching"
                # permits. At most one fallback attempt per turn, never a
                # retry loop across all providers.
                if fallback_attempted or _round_index != 0 or accumulated_text or tool_calls_this_round:
                    raise
                if not await ai_provider_settings_service.is_fallback_enabled_for_customer(
                    session, customer_id=workspace_context.customer_id
                ):
                    raise
                fallback_provider = await ai_provider_settings_service.pick_fallback_provider(
                    session,
                    customer_id=workspace_context.customer_id,
                    excluding=choice.provider,
                    settings=settings,
                )
                if fallback_provider is None:
                    raise
                fallback_attempted = True
                choice = ResolvedProviderChoice(
                    fallback_provider, default_model_for(settings, fallback_provider)
                )
                model = choice.model or ""
                gateway = get_gateway(fallback_provider, settings)
    except Exception:
        # ANY failure mid-turn (a provider error, or an unexpected bug)
        # must still reconcile the reservation down to whatever usage was
        # really incurred before re-raising — otherwise a crash leaves a
        # phantom reservation that permanently eats into the customer's
        # budget for no real spend (reserve_budget's own "give the
        # estimate back on failure" contract, generalized past just
        # ModelGatewayError so an unrelated bug can't bypass it too).
        actual_cost_cents = estimate_cost_cents(
            choice.provider,
            model,
            input_tokens=total_usage.input_tokens,
            output_tokens=total_usage.output_tokens,
        )
        await ai_budget_service.reconcile_budget(
            session,
            customer_id=workspace_context.customer_id,
            estimated_cost_cents=total_estimate_cents,
            actual_cost_cents=actual_cost_cents,
        )
        raise

    actual_cost_cents = estimate_cost_cents(
        choice.provider, model, input_tokens=total_usage.input_tokens, output_tokens=total_usage.output_tokens
    )
    await ai_budget_service.reconcile_budget(
        session,
        customer_id=workspace_context.customer_id,
        estimated_cost_cents=total_estimate_cents,
        actual_cost_cents=actual_cost_cents,
    )
    await ai_budget_service.record_usage_event(
        session,
        customer_id=workspace_context.customer_id,
        workspace_id=workspace_context.workspace_id,
        conversation_id=conversation.id,
        trace_id=trace_id,
        actor_id=f"user:{workspace_context.user_id}",
        provider=choice.provider,
        model=model,
        mode=mode,
        usage=total_usage,
        estimated_cost_cents=total_estimate_cents,
        actual_cost_cents=actual_cost_cents,
    )

    yield TurnChunk(kind="done", message=final_assistant_message)
