"""`_read_bounded` (api/knowledge.py) — proves it stops reading as soon
as the running total crosses the limit, rather than draining the whole
stream first (`file.read()` with no size argument buffers everything
before `validate_file`'s own size check ever runs — a client could
force the server to hold an arbitrarily large body just to reject it).

Uses a stub that behaves like an effectively endless stream (each
`read(n)` call always returns `n` bytes) — the real regression this
guards against is a naive `while True: read(); accumulate` loop draining
such a stream forever. A real HTTP test can't distinguish "reads the
whole body then checks" from "checks as it reads" when the body is
finite, since both reject the request either way; this can.
"""

import pytest

from doda.api.knowledge import _READ_CHUNK_BYTES, _read_bounded
from doda.domain.knowledge.file_validation import FileTooLargeError


class _EndlessStream:
    """Simulates a stream far larger than any reasonable file: every
    `read(n)` call succeeds and returns exactly `n` bytes, forever."""

    def __init__(self) -> None:
        self.calls = 0

    async def read(self, size: int) -> bytes:
        self.calls += 1
        return b"x" * size


async def test_stops_after_a_bounded_number_of_chunks_not_at_end_of_stream() -> None:
    stream = _EndlessStream()
    with pytest.raises(FileTooLargeError):
        await _read_bounded(stream, max_size_bytes=10)  # type: ignore[arg-type]

    # One chunk (1 MiB) already exceeds a 10-byte limit, so this must
    # raise on the very first read - never loop toward "end of stream"
    # (which, for this stub, would never come).
    assert stream.calls == 1


async def test_reads_multiple_chunks_when_the_limit_spans_more_than_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Shrink the chunk size so a limit larger than one chunk forces a
    # second read - proving the accumulation-across-calls path, not
    # just the immediate-first-chunk-fails path above.
    monkeypatch.setattr("doda.api.knowledge._READ_CHUNK_BYTES", 4)
    stream = _EndlessStream()
    with pytest.raises(FileTooLargeError):
        await _read_bounded(stream, max_size_bytes=10)  # type: ignore[arg-type]

    # 4 + 4 = 8 (under limit), 4 + 4 + 4 = 12 (over) - three calls, not
    # one, and nowhere near an unbounded loop.
    assert stream.calls == 3


async def test_returns_the_exact_bytes_when_under_the_limit() -> None:
    class _FiniteStream:
        def __init__(self, data: bytes) -> None:
            self._remaining = data

        async def read(self, size: int) -> bytes:
            chunk, self._remaining = self._remaining[:size], self._remaining[size:]
            return chunk

    data = b"hello world"
    result = await _read_bounded(_FiniteStream(data), max_size_bytes=1024)  # type: ignore[arg-type]
    assert result == data


def test_chunk_size_is_a_real_bound_not_unbounded() -> None:
    assert 0 < _READ_CHUNK_BYTES <= 8 * 1024 * 1024
