"""Conversation lifecycle — FR-CONV, scaffolding (see
doda.domain.conversation.models and doda.ai.port for why). Same
workspace-scoped shape as task_service.py: every query here filters by
workspace_id explicitly (6.2/NFR-ISO-002), never relies on RLS alone.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.ai.port import AIPort
from doda.domain.conversation.models import Conversation, Message, MessageRole

MAX_PAGE_SIZE = 200


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


async def post_message(
    session: AsyncSession,
    conversation: Conversation,
    *,
    actor_id: str,
    content: str,
    ai_port: AIPort,
) -> tuple[Message, Message]:
    """Writes the user's message, then the AI reply, in the same
    transaction — there is no outbox/approval step here because nothing
    external happens yet (doda.ai.port.NullAIPort never leaves the
    process); once a real provider is wired in, whether that call needs
    to move outside this transaction (timeout handling, FR-CONV-002's
    cancel) is a decision for that change, not this scaffolding."""
    user_message = Message(
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content=content,
    )
    session.add(user_message)
    await session.flush()

    history = await list_messages(session, conversation_id=conversation.id)
    reply_text = await ai_port.generate_reply(conversation_history=[m.content for m in history])

    assistant_message = Message(
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=reply_text,
    )
    session.add(assistant_message)
    await session.flush()
    return user_message, assistant_message
