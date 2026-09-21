"""doda.ai.errors.parse_retry_after_header — a pure function shared by
every gateway adapter's rate-limit translation (openai_gateway.py,
claude_gateway.py), but never given its own dedicated test: the existing
rate-limit tests in each gateway's own test file only ever exercise the
happy path (a valid numeric header present), leaving every early-return
branch here unexercised.
"""

from types import SimpleNamespace

from doda.ai.errors import parse_retry_after_header


def test_returns_none_when_the_exception_has_no_response_attribute() -> None:
    assert parse_retry_after_header(Exception("boom")) is None


def test_returns_none_when_the_response_has_no_headers_attribute() -> None:
    exc = SimpleNamespace(response=SimpleNamespace())
    assert parse_retry_after_header(exc) is None  # type: ignore[arg-type]


def test_returns_none_when_the_retry_after_header_is_absent() -> None:
    exc = SimpleNamespace(response=SimpleNamespace(headers={}))
    assert parse_retry_after_header(exc) is None  # type: ignore[arg-type]


def test_returns_none_when_the_retry_after_header_is_not_a_number() -> None:
    exc = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "not-a-number"}))
    assert parse_retry_after_header(exc) is None  # type: ignore[arg-type]


def test_returns_the_parsed_seconds_when_a_valid_header_is_present() -> None:
    exc = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "12.5"}))
    assert parse_retry_after_header(exc) == 12.5  # type: ignore[arg-type]
