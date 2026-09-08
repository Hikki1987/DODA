"""Shared error envelope — 11.2: "Xato konverti: code, xavfsiz message,
trace_id, retryable, field_errors." Every exception handler here maps a
domain/application exception to this one shape so API clients never have to
special-case response bodies per endpoint.
"""

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from doda.application.action_service import ApprovalInvalidError
from doda.application.authz_service import AuthorizationError
from doda.application.session_service import SessionInvalidError
from doda.domain.action.state_machine import InvalidActionTransition
from doda.domain.security.decisions import Decision


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
