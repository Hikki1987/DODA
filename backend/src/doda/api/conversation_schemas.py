import uuid
from datetime import datetime

from pydantic import BaseModel

from doda.domain.conversation.models import MessageRole


class CreateConversationRequest(BaseModel):
    title: str | None = None


class PostMessageRequest(BaseModel):
    content: str


class ConversationOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    owner_id: str
    title: str | None
    created_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
