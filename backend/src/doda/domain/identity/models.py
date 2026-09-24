"""Identity domain — FR-AUTH. Root aggregates: User, Session.

DODA never stores a password (FR-AUTH-001): only the hash of the OIDC
subject claim, used to correlate returning logins without holding the
provider's raw subject value at rest longer than necessary for lookup.

Neither User nor Session carries customer_id — identity is global, a user
joins customers via CustomerMembership (FR-WKS-003) — so neither table is
RLS-scoped, consistent with the Customer/Workspace tables being the first
tenant-scoped boundary.

ServiceActorCredential (FR-AUTH-009) is the one exception: it does carry a
customer_id, because a machine credential belongs to exactly one customer,
the way a CustomerMembership does. It is still an *authentication*
artifact — how a Session came to exist, same bucket as "the OIDC callback
minted this session" — not a membership; the machine actor's actual
workspace access still goes through an ordinary CustomerMembership row
(FR-WKS-003's "the only bridge" stays true), created alongside it. Kept
deliberately exempt from RLS (see doda.domain.workspace.models.
WorkspaceTenantIndex's docstring for the same chicken-and-egg reasoning):
verifying a presented secret has to happen *before* any customer_id is
known, so the lookup cannot run inside a tenant_scoped_session.
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


class ActorKind(enum.StrEnum):
    """FR-AUTH-009 / 2.2's role table: a Session is minted either for a
    human (the OIDC callback, or the dev/test seam standing in for it) or
    for a machine (doda.application.service_actor_service.
    authenticate_service_actor). 2.2's own invariant box — "Service Actor
    hech qachon approval bera olmaydi va step-up authentication o'tay
    olmaydi" — is enforced by reading this field, not by role: a Service
    Actor's CustomerMembership role is plain MEMBER (see
    ServiceActorCredential's docstring), so the restriction has to live
    here, orthogonal to role, or a WorkspaceAdmin-equivalent role on the
    machine's membership row would silently grant it approval rights.
    """

    HUMAN = "human"
    SERVICE = "service"


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
    actor_kind: Mapped[ActorKind] = mapped_column(
        SAEnum(ActorKind, name="actor_kind", native_enum=False, length=8),
        default=ActorKind.HUMAN,
        server_default=ActorKind.HUMAN.value,
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


class ServiceActorCredential(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """FR-AUTH-009: a machine credential a CustomerOwner mints for their
    own customer. `secret_hash` is a plain sha256 of a 256-bit random
    token (doda.application.identity_service.hash_oidc_subject's own
    convention) — high enough entropy that a fast, unsalted hash is fine
    for a lookup key, unlike a human password. The plaintext secret is
    returned exactly once, at creation (same one-time-reveal shape as
    Approval.nonce), and never stored or logged anywhere thereafter.

    `user_id` points at an ordinary identity_users row created alongside
    it (not a real OIDC identity, never used for OIDC login) so the
    machine actor can hold a normal CustomerMembership/WorkspaceMembership
    and flow through every existing authorize_* function unmodified —
    the only behavioral difference is carried by the Session's own
    actor_kind, checked independently of role (see ActorKind's docstring).
    """

    __tablename__ = "service_actor_credentials"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id"))
    name: Mapped[str] = mapped_column(String(256))
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
