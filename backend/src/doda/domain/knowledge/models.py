"""Knowledge domain — FR-KNW. FR-KNW-001 only: a validated file has been
accepted and stored (doda.storage.port.ObjectStoragePort). Parsing,
chunking, embedding and retrieval (FR-KNW-002 onward) do not exist yet —
they need a real, reachable AI-provider embedding call this environment
cannot make (see CLAUDE.md). A row here never represents a rejected
upload: validation (doda.domain.knowledge.file_validation) runs and can
raise BEFORE any Document is constructed, so this table only ever holds
files that passed it.
"""

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Document(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "knowledge_documents"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    uploader_id: Mapped[str] = mapped_column(String(256))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int]
    # sha256 of the file's own bytes — an integrity checksum, not a
    # dedup key (two different uploads of the same content are allowed
    # to become two different Document rows; TRD does not ask for
    # dedup and inventing that behavior would be a change request,
    # QOIDA 2).
    sha256: Mapped[str] = mapped_column(String(64))
    # doda.domain.knowledge.file_validation.storage_key_for's output —
    # never derived from the caller-supplied filename.
    storage_key: Mapped[str] = mapped_column(String(256))
