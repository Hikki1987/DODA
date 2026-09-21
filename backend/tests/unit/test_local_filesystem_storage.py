import pytest

from doda.storage.local_filesystem import LocalFilesystemObjectStorage
from doda.storage.port import ObjectNotFoundError


async def test_put_then_get_round_trips_the_exact_bytes(tmp_path) -> None:
    storage = LocalFilesystemObjectStorage(tmp_path)
    await storage.put("some/key", b"hello world")
    assert await storage.get("some/key") == b"hello world"


async def test_get_of_a_missing_key_raises_object_not_found(tmp_path) -> None:
    storage = LocalFilesystemObjectStorage(tmp_path)
    with pytest.raises(ObjectNotFoundError):
        await storage.get("never-written")


async def test_delete_of_a_missing_key_raises_object_not_found(tmp_path) -> None:
    storage = LocalFilesystemObjectStorage(tmp_path)
    with pytest.raises(ObjectNotFoundError):
        await storage.delete("never-written")


async def test_delete_removes_the_object(tmp_path) -> None:
    storage = LocalFilesystemObjectStorage(tmp_path)
    await storage.put("some/key", b"data")
    await storage.delete("some/key")
    with pytest.raises(ObjectNotFoundError):
        await storage.get("some/key")


async def test_a_path_traversal_looking_key_never_escapes_the_base_dir(tmp_path) -> None:
    """The key is hashed into the on-disk path (see the class's own
    docstring) — a value that LOOKS like a traversal attempt is just an
    opaque string to hash, not a path component, so it cannot land
    outside tmp_path regardless of what doda.domain.knowledge.
    file_validation already refuses to construct upstream."""
    storage = LocalFilesystemObjectStorage(tmp_path)
    malicious_key = "../../../etc/passwd"
    await storage.put(malicious_key, b"payload")

    written_files = list(tmp_path.rglob("*"))
    written_files = [p for p in written_files if p.is_file()]
    assert len(written_files) == 1
    assert tmp_path in written_files[0].parents
    assert await storage.get(malicious_key) == b"payload"
