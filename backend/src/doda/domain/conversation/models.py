"""Conversation domain — FR-CONV, scaffolding only (see CLAUDE.md: AI
provider and OD-003 data-classification are both still Product Owner
decisions, not yet made). This module exists so the data model and
tenant-isolation shape are in place and tested before either of those
decisions lands — adding the real model call later is then a change to
doda.ai/doda.application.conversation_service, not a new domain.

FR-CONV-003 ("Suhbat qat'iy workspace scope'ida") is the one requirement
this scaffolding can actually satisfy today, the same way Task/Action do
it: customer_id + workspace_id columns, RLS (ADR-005), and a repository
query that always filters by workspace_id (6.2/NFR-ISO-002) — no content,
retrieval or cross-workspace leak is possible structurally, independent
of whether a model is ever wired in.
"""

import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class MessageRole(enum.StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class Conversation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "conversation_conversations"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[str] = mapped_column(String(256))
    title: Mapped[str | None] = mapped_column(String(256), default=None)


class Message(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "conversation_messages"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_conversations.id"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        SAEnum(MessageRole, name="conversation_message_role", native_enum=False, length=16)
    )
    # FR-CONV content itself is deliberately free text (a chat message) —
    # unlike Action's safe_metadata (see tests/unit/test_audit_redaction.py),
    # this table is NOT audited and the Master Instruction's "prompt
    # kontentini audit/logga yozma" rule is honored by construction: no
    # code path in this scaffolding ever passes a Message's content to
    # record_audit_event.
    content: Mapped[str] = mapped_column(Text)
