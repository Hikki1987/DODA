"""Conversation endpoints — FR-CONV scaffolding. Same authoritative-chain
pattern as api/tasks.py: every handler gets its tenant/authz context only
from RequestContext, and the AI reply comes from doda.ai.port.NullAIPort
(see that module's docstring for why a real provider isn't wired in yet).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from doda.ai.port import NullAIPort
from doda.api.conversation_schemas import (
    ConversationOut,
    CreateConversationRequest,
    MessageOut,
    PostMessageRequest,
)
from doda.api.dependencies import RequestContext, get_request_context
from doda.application.authz_service import authorize_use_chat
from doda.application.conversation_service import (
    list_conversations_for_workspace,
    list_messages,
    post_message,
    start_conversation,
)
from doda.domain.conversation.models import Conversation, Message

router = APIRouter(tags=["conversations"])

# Scaffolding-only: there is exactly one AI port implementation today
# (see doda.ai.port), so handlers share one instance rather than take it
# via DI — swapping in a real provider later is the point at which this
# becomes a FastAPI dependency instead.
_ai_port = NullAIPort()


def _to_conversation_out(conversation: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        owner_id=conversation.owner_id,
        title=conversation.title,
        created_at=conversation.created_at,
    )


def _to_message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
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
    "/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
)
async def post_conversation_message(
    conversation_id: uuid.UUID,
    body: PostMessageRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> list[MessageOut]:
    authorize_use_chat(ctx.workspace)
    conversation = await _get_owned_conversation(ctx, conversation_id)
    user_message, assistant_message = await post_message(
        ctx.db,
        conversation,
        actor_id=f"user:{ctx.workspace.user_id}",
        content=body.content,
        ai_port=_ai_port,
    )
    return [_to_message_out(user_message), _to_message_out(assistant_message)]
