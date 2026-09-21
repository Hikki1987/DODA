"""FR-KNW-001's object-storage seam — the same "port + factory, one real
adapter selected by config" shape as `doda.ai.port`/`doda.ai.factory`.
`doda.application.knowledge_service` talks only to this Protocol, never
to a filesystem or an S3 SDK directly (6.2: application code does not
reach across a layer boundary to a concrete infrastructure detail).

`docker-compose.yml` already provisions a MinIO service
(`object-storage`, matching TRD 6.3's "S3-mos object storage" stack
decision) and `Settings.object_storage_endpoint`/`object_storage_bucket`
already exist for it — but this sandbox has no running Docker daemon and
no `boto3` installed, so an S3-backed adapter cannot be built and
genuinely verified here (the same "cannot reach it, so don't fake it"
constraint already documented for Telegram/Google OIDC/GCP). Rather than
write untested S3 code, v1 ships `LocalFilesystemObjectStorage` as the
one real, fully-verified implementation — appropriate for OD-001's
"personal use today" scope — and this Protocol is the seam a real
`S3ObjectStorage` adapter drops into later without touching
`knowledge_service` or its tests, mirroring exactly how `NullModelGateway`
was replaced by real provider adapters without changing
`conversation_service`.
"""

import typing


@typing.runtime_checkable
class ObjectStoragePort(typing.Protocol):
    """`key` is an opaque, caller-chosen identifier (knowledge_service
    derives it from customer_id/workspace_id/document_id, never from
    caller-supplied input) — an implementation must not interpret it as
    a shell path, URL, or anything else beyond "a name to store bytes
    under", so callers may not embed traversal sequences and expect
    protection from the port itself; sanitization is the caller's job
    (see `doda.domain.knowledge.file_validation`)."""

    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class ObjectNotFoundError(Exception):
    """Raised by `get`/`delete` when `key` does not exist — every
    adapter must raise this same type regardless of its own backend's
    native "not found" error, so `knowledge_service` never has to know
    which adapter it is talking to."""
