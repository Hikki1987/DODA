"""Typed errors for the AI layer. `doda.infrastructure.openai_gateway`
(or any future provider adapter) must raise only these — never let a raw
SDK exception escape into `application/conversation_service.py` — so the
API error envelope (`api/errors.py`) and any retry logic work against a
stable, provider-neutral set of types, same discipline as
`doda.infrastructure.telegram_client`'s `TelegramSendError`.

None of these ever carry the provider API key or a raw request/response
dump in their message — adapters must extract only structured, safe
fields (status code, provider-assigned error code, retry-after seconds),
never `str(exc)` on an SDK exception. See
tests/unit/test_openai_gateway.py for the regression test proving this.
"""


class ModelGatewayError(Exception):
    """Base for every error this layer raises."""


class ModelNotConfiguredError(ModelGatewayError):
    """No provider is configured (no API key) — not a provider failure,
    a deployment/configuration one. `doda.ai.port.NullModelGateway` is
    used instead of raising this at call sites that tolerate a stand-in
    reply; this is raised only where a real provider was specifically
    required and isn't available."""


class ModelTimeoutError(ModelGatewayError):
    """The provider did not respond within the configured timeout.
    Retryable by the caller, within the no-retry-after-first-byte rule
    documented in `doda.ai.types.GatewayErrorEvent`."""


class ModelRateLimitedError(ModelGatewayError):
    """HTTP 429 or an equivalent provider-reported rate limit.
    `retry_after_seconds` is the provider's own hint when it gave one."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ModelProviderError(ModelGatewayError):
    """Any other provider-side failure (5xx, malformed response, etc.)
    that isn't one of the more specific cases above."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ModelAuthenticationError(ModelGatewayError):
    """The configured API key was rejected by the provider. Distinct from
    ModelNotConfiguredError (no key at all) — this is a real, present but
    invalid credential, which a caller must never retry."""


class BudgetExceededError(ModelGatewayError):
    """Raised by `doda.application.ai_budget_service` before any provider
    call is made — not by a gateway adapter. Kept in this module (rather
    than application/) so `api/errors.py` can import every AI-related
    error from one place."""

    def __init__(self, message: str, *, scope: str) -> None:
        super().__init__(message)
        self.scope = scope


class OutboundContentBlockedError(ModelGatewayError):
    """Raised by `doda.application.conversation_service.stream_message`
    (via `doda.ai.outbound_guard`) before the user's message is even
    persisted, let alone sent to a provider — same "before any provider
    call" placement as BudgetExceededError, kept here for the same
    reason. `label` is one of `outbound_guard`'s fixed pattern names,
    safe to surface to the client (never the matched secret text)."""

    def __init__(self, message: str, *, label: str) -> None:
        super().__init__(message)
        self.label = label


class SensitiveContentBlockedError(ModelGatewayError):
    """NFR-DATA-001c: "C4 ma'lumot tashqi providerga default taqiqlanadi"
    (OD-003). Raised by `stream_message` right after the
    `OutboundContentBlockedError` secret check, using
    `doda.ai.data_classification.classify_outbound_content` — same "block
    outright before persisting, before any provider call" placement.
    `classification` is always `DataClassification.C4_SENSITIVE` here
    (the only class this error is ever raised for), kept as a field
    rather than hardcoded so the HTTP handler doesn't need a second
    import just to echo it back."""

    def __init__(self, message: str, *, classification: str) -> None:
        super().__init__(message)
        self.classification = classification


def parse_retry_after_header(exc: Exception) -> float | None:
    """Extracts a provider SDK exception's own `retry-after` response
    header as seconds, or None if there isn't one / it isn't a valid
    number. Shared by every gateway adapter's `_translate_error` when
    building a `ModelRateLimitedError` — the openai and anthropic SDKs
    both expose the underlying HTTP response the same way
    (`exc.response.headers`), so this one function serves both rather
    than each adapter carrying its own identical copy."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
