"""FR-AUTH-009 — Service Actor uchun alohida machine credential oqimi.

2.2's own invariant: a Service Actor "interaktiv login yoki approval qila
olmaydi" (cannot do an interactive login or give an approval) and its own
max risk level is R2. This module owns the credential lifecycle (mint,
authenticate, list, revoke); the two behavioral restrictions themselves
are enforced where every other action/approval decision already lives —
doda.application.authz_service.authorize_consume_approval and
doda.application.action_service.propose_action — reading the Session's
own actor_kind, not anything new here.

Minting a credential deliberately reuses doda.application.customer_service.
invite_customer_member for the CustomerMembership/UserCustomerIndex half
(role=MEMBER — a Service Actor holds no special CustomerRole, see
doda.domain.identity.models.ActorKind's docstring) rather than writing a
second, parallel membership-creation path.
"""

import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.audit_service import record_audit_event
from doda.application.customer_service import invite_customer_member
from doda.domain.base import utcnow
from doda.domain.identity.models import ServiceActorCredential, User
from doda.domain.security.roles import CustomerRole


class ServiceActorAuthenticationError(Exception):
    """Raised for any reason a presented secret must not be trusted: no
    such credential, or a revoked one — deliberately one exception type,
    the same "don't help an attacker distinguish the reasons" shape as
    session_service.SessionInvalidError."""


def _hash_secret(secret: str) -> str:
    """A 256-bit random token (secrets.token_urlsafe(32)) has enough
    entropy that an unsalted sha256 lookup key is fine here — the same
    reasoning as identity_service.hash_oidc_subject, unlike a
    human-chosen password."""
    return hashlib.sha256(secret.encode()).hexdigest()


async def create_service_actor_credential(
    session: AsyncSession, *, customer_id: uuid.UUID, name: str, created_by: uuid.UUID
) -> tuple[ServiceActorCredential, str]:
    """Returns (record, plaintext_secret). The plaintext is shown exactly
    once — the same one-time-reveal shape as Approval.nonce — and is never
    stored or logged anywhere past this call.

    Mints a brand-new, non-OIDC User for the machine identity: its
    oidc_subject_hash is a hash of a random token, never a real provider
    subject, so it can never collide with (or be confused for) a human
    login."""
    machine_user = User(
        oidc_subject_hash=hashlib.sha256(f"service-actor:{uuid.uuid4()}".encode()).hexdigest(),
        display_name=name,
    )
    session.add(machine_user)
    await session.flush()

    await invite_customer_member(
        session,
        customer_id=customer_id,
        user_id=machine_user.id,
        role=CustomerRole.MEMBER,
        actor_id=f"user:{created_by}",
    )

    plaintext_secret = secrets.token_urlsafe(32)
    record = ServiceActorCredential(
        customer_id=customer_id,
        user_id=machine_user.id,
        name=name,
        secret_hash=_hash_secret(plaintext_secret),
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    await record_audit_event(
        session,
        customer_id=customer_id,
        trace_id=uuid.uuid4(),
        actor_id=f"user:{created_by}",
        event_type="service_actor.credential_created.v1",
        safe_metadata={"credential_id": str(record.id), "name": name},
    )
    return record, plaintext_secret


async def authenticate_service_actor(session: AsyncSession, *, secret: str) -> ServiceActorCredential:
    """Looks up by secret hash — deliberately not customer-scoped, since
    the caller presents only the opaque secret and no customer_id (the
    same bootstrap shape as resolving a bearer session id). Runs against
    the plain, non-tenant-scoped session — service_actor_credentials
    carries no RLS (see its own model docstring)."""
    record = await session.scalar(
        select(ServiceActorCredential).where(ServiceActorCredential.secret_hash == _hash_secret(secret))
    )
    if record is None or record.revoked_at is not None:
        raise ServiceActorAuthenticationError("invalid or revoked service actor credential")
    return record


async def list_service_actor_credentials(
    session: AsyncSession, *, customer_id: uuid.UUID
) -> list[ServiceActorCredential]:
    """Metadata only — the API layer never re-derives or exposes
    secret_hash. Explicit customer_id predicate even though this table
    has no RLS to fall back on as a second layer (6.2/NFR-ISO-002): here
    it is the *only* layer, not a second one."""
    result = await session.scalars(
        select(ServiceActorCredential)
        .where(ServiceActorCredential.customer_id == customer_id)
        .order_by(ServiceActorCredential.created_at)
    )
    return list(result)


async def revoke_service_actor_credential(
    session: AsyncSession, *, customer_id: uuid.UUID, credential_id: uuid.UUID, actor_id: str
) -> ServiceActorCredential | None:
    """Returns None if no such credential exists for this customer (the
    caller turns that into a 404) rather than raising — mirrors
    workspace_service's per-record tenancy-check shape elsewhere. Revoking
    an already-revoked credential is a harmless no-op (idempotent, the
    same stance as session_service.revoke_session), not audited a second
    time."""
    record = await session.scalar(
        select(ServiceActorCredential).where(
            ServiceActorCredential.id == credential_id, ServiceActorCredential.customer_id == customer_id
        )
    )
    if record is None:
        return None
    if record.revoked_at is not None:
        return record

    record.revoked_at = utcnow()
    await session.flush()
    await record_audit_event(
        session,
        customer_id=customer_id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="service_actor.credential_revoked.v1",
        safe_metadata={"credential_id": str(record.id), "name": record.name},
    )
    return record
