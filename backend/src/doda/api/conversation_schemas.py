import uuid
from datetime import datetime

from pydantic import BaseModel

from doda.ai.types import ChatMode, Provider
from doda.domain.conversation.models import MessageRole


class CreateConversationRequest(BaseModel):
    title: str | None = None


class PostMessageRequest(BaseModel):
    content: str
    mode: ChatMode = ChatMode.STANDARD


class SwitchProviderRequest(BaseModel):
    provider: Provider
    model: str | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    owner_id: str
    title: str | None
    pinned_provider: str | None
    pinned_model: str | None
    created_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    tool_call_id: str | None
    tool_name: str | None
    provider: str | None
    model: str | None
    finish_reason: str | None
    created_at: datetime
