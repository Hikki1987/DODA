"""Customer domain — FR-WKS (customer half). Root aggregate: Customer.

CustomerMembership is the only bridge between a user and a customer
(FR-WKS-003): a UserId is never attached to a workspace directly.
"""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Customer(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "customer_customers"

    name: Mapped[str] = mapped_column(String(256))


class CustomerMembership(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "customer_memberships"

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customer_customers.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(32))
    """Customer-level role: platform_owner | customer_owner | member | auditor (10.2)."""


class UserCustomerIndex(Base):
    """Deliberately NOT RLS-protected — the same bootstrap pattern as
    doda.domain.workspace.models.WorkspaceTenantIndex, one level up. A
    logged-in user (proven by session) has no way to discover which
    customers/workspaces they belong to at all otherwise: CustomerMembership
    itself has FORCE ROW LEVEL SECURITY keyed on customer_id, so querying
    "which customers is user X a member of" requires already knowing a
    customer_id to open the tenant_scoped_session in the first place — the
    exact chicken-and-egg problem WorkspaceTenantIndex solves for workspace
    resolution. This table carries nothing but the id mapping, no role or
    other content, so exposing it costs no tenant content.

    Written only by doda.application.customer_service (invite_customer_
    member, create_customer_with_owner, remove_customer_member), in the
    same transaction as the CustomerMembership row it mirrors — never
    written to directly, so it cannot drift from the source of truth. A
    user can appear at most once per customer (matches one CustomerMembership
    row per (user_id, customer_id) being the intended shape, even though
    that isn't a DB-enforced uniqueness on CustomerMembership itself).
    """

    __tablename__ = "user_customer_index"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, index=True)
