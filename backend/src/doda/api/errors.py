"""Shared error envelope — 11.2: "Xato konverti: code, xavfsiz message,
trace_id, retryable, field_errors." Every exception handler here maps a
domain/application exception to this one shape so API clients never have to
special-case response bodies per endpoint.
"""

import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from doda.ai.capabilities import UnsupportedModelCapabilityError
from doda.ai.errors import (
    BudgetExceededError,
    ModelAuthenticationError,
    ModelNotConfiguredError,
    ModelProviderError,
    ModelRateLimitedError,
    ModelTimeoutError,
)
from doda.api.middleware import TRACE_ID_HEADER
from doda.application.action_service import ApprovalInvalidError
from doda.application.ai_provider_settings_service import ProviderDisabledError
from doda.application.authz_service import AuthorizationError
from doda.application.conversation_service import DeepRequestCostCeilingExceededError
from doda.application.customer_service import CustomerMembershipError, DuplicateMembershipError
from doda.application.kill_switch_service import KillSwitchEngagedError
from doda.application.notification_service import NotificationPreferenceError
from doda.application.oidc_login_service import OidcNotConfiguredError, OidcStateMismatchError
from doda.application.session_service import SessionInvalidError
from doda.application.task_service import InvalidTaskTransition, TaskParentNotFoundError
from doda.application.workspace_service import DuplicateWorkspaceMembershipError, WorkspaceMembershipError
from doda.domain.action.state_machine import InvalidActionTransition
from doda.domain.security.decisions import Decision
from doda.infrastructure.google_oidc_client import GoogleOidcError


def _envelope(
    *, code: str, message: str, trace_id: str, retryable: bool, field_errors: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "trace_id": trace_id,
        "retryable": retryable,
        "field_errors": field_errors or {},
    }


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", str(uuid.uuid4()))


logger = structlog.get_logger()


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionInvalidError)
    async def _session_invalid(request: Request, exc: SessionInvalidError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=_envelope(
                code="UNAUTHENTICATED",
                message="Sessiya yaroqsiz. Qayta tizimga kiring.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(AuthorizationError)
    async def _authorization_error(request: Request, exc: AuthorizationError) -> JSONResponse:
        # 10.1: sezgir tafsilot ko'rsatilmaydi — exc's real reason stays
        # server-side (it reached this handler, so it's in the traceback/
        # logs); the client only gets the decision code.
        status_code = 403
        message = "Ruxsat berilmadi."
        if exc.decision is Decision.STEP_UP_REQUIRED:
            message = "Ushbu amal uchun qayta autentifikatsiya (MFA) talab qilinadi."
        return JSONResponse(
            status_code=status_code,
            content=_envelope(
                code=exc.decision.value,
                message=message,
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(InvalidActionTransition)
    async def _invalid_transition(request: Request, exc: InvalidActionTransition) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_envelope(
                code="INVALID_STATE",
                message="Action holati bu amalni qabul qilmaydi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(InvalidTaskTransition)
    async def _invalid_task_transition(request: Request, exc: InvalidTaskTransition) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_envelope(
                code="INVALID_STATE",
                message="Task holati bu amalni qabul qilmaydi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(TaskParentNotFoundError)
    async def _task_parent_not_found(request: Request, exc: TaskParentNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_envelope(
                code="NOT_FOUND",
                message="Parent task topilmadi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(ApprovalInvalidError)
    async def _approval_invalid(request: Request, exc: ApprovalInvalidError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_envelope(
                code="APPROVAL_INVALID",
                message="Approval qabul qilinmadi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(WorkspaceMembershipError)
    async def _workspace_membership_error(request: Request, exc: WorkspaceMembershipError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_envelope(
                code="MEMBERSHIP_INVALID",
                message="A'zolik amali bajarilmadi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(CustomerMembershipError)
    async def _customer_membership_error(request: Request, exc: CustomerMembershipError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_envelope(
                code="LAST_OWNER_PROTECTED",
                message="Oxirgi Customer Owner'ni chiqarib yoki lavozimini pasaytirib bo'lmaydi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(DuplicateMembershipError)
    async def _duplicate_membership_error(request: Request, exc: DuplicateMembershipError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_envelope(
                code="ALREADY_MEMBER",
                message="Bu foydalanuvchi allaqachon a'zo.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(DuplicateWorkspaceMembershipError)
    async def _duplicate_workspace_membership_error(
        request: Request, exc: DuplicateWorkspaceMembershipError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_envelope(
                code="ALREADY_MEMBER",
                message="Bu foydalanuvchi allaqachon shu workspace'ning a'zosi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(NotificationPreferenceError)
    async def _notification_preference_error(
        request: Request, exc: NotificationPreferenceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_envelope(
                code="SECURITY_ALERT_MANDATORY",
                message="Security alert turdagi bildirishnomani o'chirib bo'lmaydi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(KillSwitchEngagedError)
    async def _kill_switch_engaged(request: Request, exc: KillSwitchEngagedError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content=_envelope(
                code="KILL_SWITCH_ENGAGED",
                message=f"{exc.scope.capitalize()} darajasida kill switch faol — yangi actionlar bloklangan.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(OidcNotConfiguredError)
    async def _oidc_not_configured(request: Request, exc: OidcNotConfiguredError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=_envelope(
                code="OIDC_NOT_CONFIGURED",
                message="Google login bu muhitda sozlanmagan.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(OidcStateMismatchError)
    async def _oidc_state_mismatch(request: Request, exc: OidcStateMismatchError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=_envelope(
                code="OIDC_STATE_MISMATCH",
                message="Login muddati tugagan yoki noto'g'ri so'rov. Qaytadan urinib ko'ring.",
                trace_id=_trace_id(request),
                retryable=True,
            ),
        )

    @app.exception_handler(GoogleOidcError)
    async def _google_oidc_error(request: Request, exc: GoogleOidcError) -> JSONResponse:
        # 10.1: the real reason (exc's own message — never the client
        # secret or an access token, see google_oidc_client.py's module
        # docstring) stays server-side; the client gets a generic message.
        logger.warning("google_oidc_error", trace_id=_trace_id(request), reason=str(exc))
        return JSONResponse(
            status_code=502,
            content=_envelope(
                code="OIDC_PROVIDER_ERROR",
                message="Google bilan bog'lanishda xato yuz berdi. Qaytadan urinib ko'ring.",
                trace_id=_trace_id(request),
                retryable=True,
            ),
        )

    @app.exception_handler(BudgetExceededError)
    async def _budget_exceeded(request: Request, exc: BudgetExceededError) -> JSONResponse:
        return JSONResponse(
            status_code=402,
            content=_envelope(
                code="BUDGET_EXCEEDED",
                message="Oylik AI byudjeti tugadi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(DeepRequestCostCeilingExceededError)
    async def _deep_cost_ceiling_exceeded(
        request: Request, exc: DeepRequestCostCeilingExceededError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=402,
            content=_envelope(
                code="DEEP_COST_CEILING_EXCEEDED",
                message="Bu so'rov DEEP rejimning bitta so'rov uchun narx chegarasidan oshadi.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(ModelNotConfiguredError)
    async def _model_not_configured(request: Request, exc: ModelNotConfiguredError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=_envelope(
                code="AI_PROVIDER_NOT_CONFIGURED",
                message="Tanlangan AI provayder sozlanmagan.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(ModelAuthenticationError)
    async def _model_authentication_error(request: Request, exc: ModelAuthenticationError) -> JSONResponse:
        # 10.1: the real reason (a rejected key) stays server-side; never
        # echo the provider's own message, which could describe the key.
        logger.warning("ai_provider_authentication_error", trace_id=_trace_id(request))
        return JSONResponse(
            status_code=502,
            content=_envelope(
                code="AI_PROVIDER_AUTH_ERROR",
                message="AI provayder kalitini qabul qilmadi. Administrator bilan bog'laning.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(ModelRateLimitedError)
    async def _model_rate_limited(request: Request, exc: ModelRateLimitedError) -> JSONResponse:
        headers = {}
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(round(exc.retry_after_seconds))
        return JSONResponse(
            status_code=429,
            content=_envelope(
                code="AI_PROVIDER_RATE_LIMITED",
                message="AI provayder vaqtincha band. Birozdan so'ng qayta urinib ko'ring.",
                trace_id=_trace_id(request),
                retryable=True,
            ),
            headers=headers,
        )

    @app.exception_handler(ModelTimeoutError)
    async def _model_timeout(request: Request, exc: ModelTimeoutError) -> JSONResponse:
        return JSONResponse(
            status_code=504,
            content=_envelope(
                code="AI_PROVIDER_TIMEOUT",
                message="AI provayderdan javob kutish vaqti tugadi.",
                trace_id=_trace_id(request),
                retryable=True,
            ),
        )

    @app.exception_handler(ModelProviderError)
    async def _model_provider_error(request: Request, exc: ModelProviderError) -> JSONResponse:
        logger.warning("ai_provider_error", trace_id=_trace_id(request), status_code=exc.status_code)
        return JSONResponse(
            status_code=502,
            content=_envelope(
                code="AI_PROVIDER_ERROR",
                message="AI provayder bilan bog'lanishda xato yuz berdi.",
                trace_id=_trace_id(request),
                retryable=True,
            ),
        )

    @app.exception_handler(UnsupportedModelCapabilityError)
    async def _unsupported_model_capability(
        request: Request, exc: UnsupportedModelCapabilityError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                code="AI_CAPABILITY_UNSUPPORTED",
                message=str(exc),
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(ProviderDisabledError)
    async def _provider_disabled(request: Request, exc: ProviderDisabledError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content=_envelope(
                code="AI_PROVIDER_DISABLED",
                message=f"{exc.provider.value} bu customer uchun o'chirilgan.",
                trace_id=_trace_id(request),
                retryable=False,
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all so an unexpected bug still returns 11.2's one envelope
        shape instead of FastAPI/Starlette's own default body (a different,
        undocumented shape) — and so it leaves a trace_id-correlated log
        line, not just a client-visible failure with no server-side record.
        This does not shadow the handlers above: Starlette dispatches by the
        most specific registered exception type in the MRO, so every
        `exception_handler` registered earlier in this function still wins
        for its own exception type.

        Sets `X-Trace-Id` itself rather than relying on `TraceIdMiddleware`:
        Starlette routes a handler registered for the bare `Exception` type
        to `ServerErrorMiddleware`, which sits OUTSIDE every user middleware
        (including `TraceIdMiddleware`) — proven by a test that this response
        would otherwise ship with a `trace_id` in its JSON body but no
        `X-Trace-Id` header at all, unlike every other error response.
        """
        trace_id = _trace_id(request)
        logger.exception("unhandled_exception", trace_id=trace_id, path=request.url.path)
        return JSONResponse(
            status_code=500,
            content=_envelope(
                code="INTERNAL_ERROR",
                message="Kutilmagan xato yuz berdi.",
                trace_id=trace_id,
                retryable=True,
            ),
            headers={TRACE_ID_HEADER: trace_id},
        )
