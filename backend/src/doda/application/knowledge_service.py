"""FR-KNW-001: file ingest. `ingest_file` is the one function that
validates (doda.domain.knowledge.file_validation), stores
(doda.storage.port.ObjectStoragePort) and records (Document row) an
upload — a caller never does any of those three steps on its own.

Ordering note (accepted, documented limitation, not a gap this task
closes): storage happens BEFORE the Document row is inserted, so a
crash between the two leaves an orphaned object with no DB row pointing
at it (harmless — nothing can ever reach it) rather than a DB row
pointing at a file that was never written (which would be a broken
reference every read of it hits). The reverse ordering trades one
failure mode for the other; this one was chosen because it fails safe.
"""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.domain.knowledge.file_validation import storage_key_for, validate_file
from doda.domain.knowledge.models import Document
from doda.storage.port import ObjectStoragePort

MAX_PAGE_SIZE = 200


async def ingest_file(
    session: AsyncSession,
    storage: ObjectStoragePort,
    *,
    customer_id: uuid.UUID,
    workspace_id: uuid.UUID,
    uploader_id: str,
    filename: str,
    declared_content_type: str,
    data: bytes,
    max_size_bytes: int,
) -> Document:
    content_type = validate_file(
        filename=filename,
        declared_content_type=declared_content_type,
        data=data,
        max_size_bytes=max_size_bytes,
    )
    document_id = uuid.uuid4()
    storage_key = storage_key_for(customer_id=customer_id, workspace_id=workspace_id, document_id=document_id)
    await storage.put(storage_key, data)

    document = Document(
        id=document_id,
        customer_id=customer_id,
        workspace_id=workspace_id,
        uploader_id=uploader_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=storage_key,
    )
    session.add(document)
    await session.flush()
    return document


async def list_documents_for_workspace(
    session: AsyncSession, *, workspace_id: uuid.UUID, limit: int = 50
) -> list[Document]:
    result = await session.scalars(
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
        .limit(min(limit, MAX_PAGE_SIZE))
    )
    return list(result.all())


async def delete_document(session: AsyncSession, storage: ObjectStoragePort, document: Document) -> None:
    """Deletes the DB row first, then the stored object — the same
    fail-safe direction as ingest_file's own ordering note: a crash
    between the two leaves an orphaned object with no row pointing at
    it, never a row pointing at a file that no longer exists."""
    await session.delete(document)
    await session.flush()
    await storage.delete(document.storage_key)
