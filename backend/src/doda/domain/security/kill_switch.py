"""Kill switch — FR-CTL-003, 10.2's "Kill switch" row (Workspace: workspace_admin,
Customer: customer_owner). A row's mere EXISTENCE means "engaged"; disengaging
deletes it, so the hot-path check in doda.application.kill_switch_service is
one cheap existence lookup per scope, not a boolean-flag comparison that could
be left in an ambiguous state.

KNOWN LIMITATION: no GLOBAL (platform-wide) switch here. FR-CTL-003 names
"Global va workspace kill switch", but a platform-wide switch is Platform
Owner territory (2.2: R5, dual control) — that role and its dual-control
approval flow don't exist in this codebase yet (FR-ADM scope). What IS
implemented — workspace and customer scope — is exactly 10.2's actual
permission-matrix row, which has no "global" column either.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base


class WorkspaceKillSwitch(Base):
    __tablename__ = "workspace_kill_switches"

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    engaged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    engaged_by: Mapped[str] = mapped_column(String(256))
    reason: Mapped[str] = mapped_column(String(512))


class CustomerKillSwitch(Base):
    __tablename__ = "customer_kill_switches"

    customer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    engaged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    engaged_by: Mapped[str] = mapped_column(String(256))
    reason: Mapped[str] = mapped_column(String(512))
