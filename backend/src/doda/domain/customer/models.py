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
