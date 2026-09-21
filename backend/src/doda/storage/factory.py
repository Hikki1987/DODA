"""Picks which `ObjectStoragePort` implementation backs file storage —
the `doda.ai.factory.get_gateway` pattern applied to object storage.
Today there is exactly one real adapter (see `doda.storage.port`'s
docstring for why); this function still exists as the single seam a
future `S3ObjectStorage` selection would go through, so
`knowledge_service` and its callers never construct an adapter directly.
"""

from functools import lru_cache

from doda.config import Settings, get_settings
from doda.storage.local_filesystem import LocalFilesystemObjectStorage
from doda.storage.port import ObjectStoragePort


@lru_cache
def _local_storage(base_dir: str) -> ObjectStoragePort:
    return LocalFilesystemObjectStorage(base_dir)


def get_object_storage(settings: Settings | None = None) -> ObjectStoragePort:
    settings = settings or get_settings()
    return _local_storage(settings.knowledge_storage_dir)
