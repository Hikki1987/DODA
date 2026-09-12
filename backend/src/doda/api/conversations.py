"""Conversation endpoints — FR-CONV. Same authoritative-chain pattern as
api/actions.py/api/tasks.py: every handler gets its tenant/authz context
only from RequestContext, and the request's own TraceIdMiddleware-minted
`request.state.trace_id` becomes the turn's trace_id (NFR-OBS-001 — see
api/actions.py's identical reasoning).

`POST .../messages` streams its reply over SSE
(`text/event-stream`) rather than returning a single JSON body, because a
chat turn may take several seconds across multiple tool-call rounds and
FR-CONV-002 expects the caller to see text as it is produced. Two error
paths, deliberately different:

- A failure BEFORE the first byte (budget exceeded, DEEP cost ceiling, or
  a provider error on the very first round) is raised as a normal Python
  exception from priming the generator's first item — at that point no
  response has been sent yet, so it is handled by the SAME registered
  exception handlers (`api/errors.py`) as every other endpoint, with a
  real 4xx/5xx status code.
- A failure AFTER the first byte cannot change the status code (HTTP
  headers are already on the wire) — Starlette would otherwise just abort
  the connection. So once streaming has started, any further
  `ModelGatewayError`/unexpected exception is caught INSIDE the SSE body
  and turned into one final `event: error` frame, then the generator ends
  normally — letting the request's transaction commit the turn's real,
  partial state (messages already produced, the budget reservation
  `conversation_service.stream_message` already reconciled down to actual
  usage before re-raising) instead of rolling all of it back.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from doda.api.conversation_schemas import (
    ConversationOut,
    CreateConversationRequest,
    MessageOut,
    PostMessageRequest,
    SwitchProviderRequest,
)
from doda.api.dependencies import RequestContext, get_request_context
from doda.application.authz_service import authorize_use_chat
from doda.application.conversation_service import (
    list_conversations_for_workspace,
    list_messages,
    start_conversation,
    stream_message,
    switch_conversation_provider,
)
from doda.config import get_settings
from doda.domain.conversation.models import Conversation, Message

router = APIRouter(tags=["conversations"])
logger = structlog.get_logger()


def _to_conversation_out(conversation: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        owner_id=conversation.owner_id,
        title=conversation.title,
        pinned_provider=conversation.pinned_provider,
        pinned_model=conversation.pinned_model,
        created_at=conversation.created_at,
    )


def _to_message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        provider=message.provider,
        model=message.model,
        finish_reason=message.finish_reason,
        created_at=message.created_at,
    )


@router.post("/v1/workspaces/{workspace_id}/conversations", response_model=ConversationOut)
async def create_conversation(
    body: CreateConversationRequest, ctx: RequestContext = Depends(get_request_context)
) -> ConversationOut:
    authorize_use_chat(ctx.workspace)
    conversation = await start_conversation(
        ctx.db,
        customer_id=ctx.workspace.customer_id,
        workspace_id=ctx.workspace.workspace_id,
        owner_id=f"user:{ctx.workspace.user_id}",
        title=body.title,
    )
    return _to_conversation_out(conversation)


@router.get("/v1/workspaces/{workspace_id}/conversations", response_model=list[ConversationOut])
async def list_workspace_conversations(
    limit: int = Query(default=50, le=200),
    ctx: RequestContext = Depends(get_request_context),
) -> list[ConversationOut]:
    authorize_use_chat(ctx.workspace)
    conversations = await list_conversations_for_workspace(
        ctx.db, workspace_id=ctx.workspace.workspace_id, limit=limit
    )
    return [_to_conversation_out(c) for c in conversations]


async def _get_owned_conversation(ctx: RequestContext, conversation_id: uuid.UUID) -> Conversation:
    conversation = await ctx.db.get(Conversation, conversation_id)
    if conversation is None or conversation.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conversation


@router.get(
    "/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
)
async def list_conversation_messages(
    conversation_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> list[MessageOut]:
    authorize_use_chat(ctx.workspace)
    conversation = await _get_owned_conversation(ctx, conversation_id)  # 404s before revealing anything
    messages = await list_messages(ctx.db, conversation_id=conversation.id)
    return [_to_message_out(m) for m in messages]


@router.post(
    "/v1/workspaces/{workspace_id}/conversations/{conversation_id}/provider", response_model=ConversationOut
)
async def switch_provider(
    conversation_id: uuid.UUID,
    body: SwitchProviderRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> ConversationOut:
    authorize_use_chat(ctx.workspace)
    conversation = await _get_owned_conversation(ctx, conversation_id)
    conversation = await switch_conversation_provider(
        ctx.db, conversation, provider=body.provider, model=body.model
    )
    return _to_conversation_out(conversation)


def _sse_frame(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def _error_frame(*, code: str, message: str, trace_id: uuid.UUID, retryable: bool) -> bytes:
    return _sse_frame(
        "error", {"code": code, "message": message, "trace_id": str(trace_id), "retryable": retryable}
    )


@router.post("/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages")
async def post_conversation_message(
    request: Request,
    conversation_id: uuid.UUID,
    body: PostMessageRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> StreamingResponse:
    authorize_use_chat(ctx.workspace)
    conversation = await _get_owned_conversation(ctx, conversation_id)
    trace_id = uuid.UUID(request.state.trace_id)

    turns = stream_message(
        ctx.db,
        conversation,
        workspace_context=ctx.workspace,
        content=body.content,
        mode=body.mode,
        trace_id=trace_id,
        settings=get_settings(),
    )

    # Prime the first item BEFORE returning the StreamingResponse: every
    # pre-stream failure (BudgetExceededError, DeepRequestCostCeilingExceededError,
    # a provider error on the very first round) raises here, while we are
    # still plain request-handling code with no response sent yet — so it
    # reaches the SAME registered exception handlers (api/errors.py) as
    # every other endpoint, with a real 4xx/5xx, instead of being silently
    # downgraded to an SSE frame no client expects before any text.
    try:
        first_chunk = await turns.__anext__()
    except StopAsyncIteration:
        first_chunk = None

    async def _body() -> AsyncIterator[bytes]:
        chunk = first_chunk
        try:
            while chunk is not None:
                if chunk.kind == "done":
                    payload = (
                        {"message": _to_message_out(chunk.message).model_dump(mode="json")}
                        if chunk.message is not None
                        else {"message": None}
                    )
                    yield _sse_frame("done", payload)
                else:
                    yield _sse_frame(chunk.kind, {"text": chunk.text})
                try:
                    chunk = await turns.__anext__()
                except StopAsyncIteration:
                    break
        except Exception as exc:  # noqa: BLE001 — see module docstring: must never escape mid-stream
            logger.exception(
                "conversation_stream_failed", trace_id=str(trace_id), error_type=type(exc).__name__
            )
            yield _error_frame(
                code="AI_STREAM_ERROR",
                message="Suhbat davomida xato yuz berdi.",
                trace_id=trace_id,
                retryable=True,
            )

    return StreamingResponse(_body(), media_type="text/event-stream")
