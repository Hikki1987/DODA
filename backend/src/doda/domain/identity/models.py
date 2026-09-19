"""Identity domain — FR-AUTH. Root aggregates: User, Session.

DODA never stores a password (FR-AUTH-001): only the hash of the OIDC
subject claim, used to correlate returning logins without holding the
provider's raw subject value at rest longer than necessary for lookup.

Neither User nor Session carries customer_id — identity is global, a user
joins customers via CustomerMembership (FR-WKS-003) — so neither table is
RLS-scoped, consistent with the Customer/Workspace tables being the first
tenant-scoped boundary.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "identity_users"

    oidc_subject_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256))


class AuthStrength(enum.StrEnum):
    """NIST-style authenticator assurance level. AAL2 is what 9.1/FR-AUTH-004
    call "fresh MFA" — R3+ actions require it at approval time."""

    AAL1 = "AAL1"
    AAL2 = "AAL2"


class Session(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """FR-AUTH-003/005/006. Created either by the real Google OIDC login
    callback (doda.application.oidc_login_service, FR-AUTH-001) or by
    doda.application.session_service.create_session's dev/test seam,
    used directly by tests and seed scripts without a real browser login."""

    __tablename__ = "identity_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id"), index=True)
    auth_strength: Mapped[AuthStrength] = mapped_column(
        SAEnum(AuthStrength, name="auth_strength", native_enum=False, length=8)
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    """Absolute timeout (FR-AUTH-006: 12h default) — independent of idle
    timeout, which is enforced by comparing last_seen_at at resolve time."""
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    """FR-AUTH-007's device signal. NULL for the dev/test seam and any
    session predating this column — session_service.is_new_device_login
    treats NULL as "no evidence", never as anomalous."""
