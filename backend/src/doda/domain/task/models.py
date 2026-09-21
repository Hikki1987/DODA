"""Task domain — FR-TASK. Root aggregate: Task.

Status changes must go through the application layer, which writes a
TaskHistory row in the same transaction (FR-TASK-007: "har status
o'zgarishi actor va vaqt bilan yoziladi") — never assign `Task.status`
directly from a repository or API handler.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class TaskStatus(enum.StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Task(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "task_tasks"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[str] = mapped_column(String(256))
    title: Mapped[str] = mapped_column(String(512))
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_tasks.id"), default=None)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=False, length=32),
        default=TaskStatus.TODO,
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class TaskHistory(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "task_history"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_tasks.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(256))
    from_status: Mapped[TaskStatus | None] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=False, length=32), default=None
    )
    to_status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=False, length=32)
    )


class ReminderStatus(enum.StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    FIRED = "FIRED"


class Reminder(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """FR-TASK-005: "Reminder yaratish so'rovi... Aniq vaqt va trigger
    foydalanuvchi tomonidan tasdiqlanadi" — a reminder REQUEST never fires
    on its own; `remind_at` only takes effect once an explicit confirm
    call (application/task_service.confirm_reminder) moves it out of
    PENDING_CONFIRMATION. Only CONFIRMED reminders are ever considered by
    the firing job (task_service.fire_due_reminders).

    "Trigger" is deliberately scoped to the one concrete, unambiguous
    reading of this requirement this codebase can build without guessing
    at a Product Owner decision: a fixed point in time the user typed in
    themselves — not a natural-language/AI-parsed trigger ("remind me
    when X happens"), which would require deciding how ambiguous phrasing
    resolves and is not something to invent here (QOIDA 2)."""

    __tablename__ = "task_reminders"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_tasks.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(256))
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[ReminderStatus] = mapped_column(
        SAEnum(ReminderStatus, name="reminder_status", native_enum=False, length=32),
        default=ReminderStatus.PENDING_CONFIRMATION,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class TaskDecision(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """FR-TASK-003: a decision record (variant considered, tradeoff,
    decision made, reason). "Qaror versiyalanadi; oldingi versiya
    o'chirilmaydi" — recording a new decision never updates or deletes an
    earlier one, it inserts another row; the DB trigger (0020-migration)
    enforces this regardless of caller, the same append-only guarantee
    audit_events already has. The current decision is simply the latest
    row for a task_id; nothing here is ever mutated in place."""

    __tablename__ = "task_decisions"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_tasks.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(256))
    variant: Mapped[str] = mapped_column(Text)
    tradeoff: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)


class TaskAttachment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """FR-TASK-006: "Task'ni evidence va fayl bilan bog'lash" — its own
    acceptance criterion is "bog'langan manba o'chirilsa task'da uzilgan
    havola belgilanadi" (if the linked source is deleted, the task shows
    a broken link), not that the link itself is immutable — unlike
    TaskDecision above, this table is a plain, detachable link, not
    append-only.

    `document_id` is deliberately a bare UUID, not a ForeignKey to
    `knowledge_documents` — that table belongs to the Knowledge domain,
    and 6.2's domain-isolation rule ("faqat ID/reference kontrakti")
    means Task may hold a reference to it but must not import or
    FK-couple to its implementation. This is the same shape
    `Notification.reference_id` already uses for cross-domain
    references: the application layer resolves it by hand and tolerates
    "not found" as a normal, expected outcome (the referenced document
    having been deleted) rather than an error — which is exactly what
    the acceptance criterion asks for."""

    __tablename__ = "task_attachments"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_tasks.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    attached_by: Mapped[str] = mapped_column(String(256))
