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
