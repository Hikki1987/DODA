"""The one real `ObjectStoragePort` implementation today (see
`doda.storage.port` for why: no Docker daemon / no `boto3` in this
sandbox to build and verify an S3 adapter against). Stores each object
as a single file under `base_dir`, split into two path segments taken
from the key's own hash so a single directory never accumulates an
unbounded number of entries (the standard "fan-out" layout).
"""

import asyncio
import hashlib
from pathlib import Path

from doda.storage.port import ObjectNotFoundError


class LocalFilesystemObjectStorage:
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def _path_for(self, key: str) -> Path:
        # `key` is caller-controlled in shape (knowledge_service builds it
        # from a document_id, but nothing here should trust that) — hashing
        # it into the on-disk path means no value of `key`, however it was
        # constructed, can ever result in a path outside `base_dir` (no
        # ".." traversal is possible against a hex digest).
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._base_dir / digest[:2] / digest[2:4] / digest

    async def put(self, key: str, data: bytes) -> None:
        path = self._path_for(key)
        await asyncio.to_thread(self._write_sync, path, data)

    def _write_sync(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes:
        path = self._path_for(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise ObjectNotFoundError(key) from None

    async def delete(self, key: str) -> None:
        path = self._path_for(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            raise ObjectNotFoundError(key) from None
