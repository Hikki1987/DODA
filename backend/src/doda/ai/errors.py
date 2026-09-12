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
