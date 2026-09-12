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
    TOOL = "TOOL"
    """The result of a tool call fed back to the model — `tool_call_id`
    links it to the ASSISTANT message that requested it (0015-migratsiya).
    """


class Conversation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "conversation_conversations"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[str] = mapped_column(String(256))
    title: Mapped[str | None] = mapped_column(String(256), default=None)

    # Set only once a user explicitly switches provider/model INSIDE this
    # conversation (0015-migratsiya) — None means "use whatever the
    # resolution chain currently says" (doda.application.
    # ai_preference_service): conversation pin > user default > workspace
    # default > system default. Pinning a conversation deliberately does
    # NOT change the user's or workspace's saved default — the explicit
    # instruction "Standart tanlovni o'zgartirish mavjud suhbatlarning
    # tanlovini avtomatik o'zgartirmasin" is symmetric: neither direction
    # auto-propagates into the other.
    pinned_provider: Mapped[str | None] = mapped_column(String(16), default=None)
    pinned_model: Mapped[str | None] = mapped_column(String(64), default=None)


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
    content: Mapped[str] = mapped_column(Text, default="")

    # --- Tool-call turns (0015-migratsiya) ------------------------------
    # An ASSISTANT message with tool_name set means "the model requested
    # this tool call" (content is usually empty); the matching TOOL
    # message carries the result, linked by tool_call_id. Deliberately
    # provider-neutral — call_id is whatever the ORIGINATING provider
    # assigned (or a synthesized one, for providers that don't), and
    # every adapter (doda.infrastructure.*_gateway) re-mints its OWN
    # native call-id shape when replaying this as history, never reusing
    # another provider's id directly — the explicit instruction "boshqa
    # provayderga to'g'ridan-to'g'ri yubormaslik" (provider-specific
    # session/call ids must not cross providers).
    tool_call_id: Mapped[str | None] = mapped_column(String(128), default=None)
    tool_name: Mapped[str | None] = mapped_column(String(128), default=None)
    tool_arguments_json: Mapped[str | None] = mapped_column(Text, default=None)

    # --- Provider/model attribution (0015-migratsiya) -------------------
    # "Har bir javobda uni yaratgan provayder va model haqidagi metadata
    # saqlansin. Oldingi javoblarning provayder yorlig'i yangi tanlov
    # sababli o'zgarmasin" — set once, at write time, on each ASSISTANT
    # message; never recomputed from the conversation's current
    # provider/model choice.
    provider: Mapped[str | None] = mapped_column(String(16), default=None)
    model: Mapped[str | None] = mapped_column(String(64), default=None)
    finish_reason: Mapped[str | None] = mapped_column(String(16), default=None)
    """FR-CONV-008: "stop"/"tool_calls"/"length"/"cancelled"/"error" — a
    "length" or "cancelled" message must be rendered as incomplete, never
    presented as a full answer."""
