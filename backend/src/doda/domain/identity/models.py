"""Identity domain — FR-AUTH. Root aggregate: User.

DODA never stores a password (FR-AUTH-001): only the hash of the OIDC
subject claim, used to correlate returning logins without holding the
provider's raw subject value at rest longer than necessary for lookup.
"""

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "identity_users"

    oidc_subject_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256))
