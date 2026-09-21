"""Per-request trace_id — 11.2: "Har request trace_id oladi." Generated here
so it exists even for requests that fail before reaching a handler (e.g. a
dependency raises), and echoed back as a response header for client-side
correlation with server logs.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

TRACE_ID_HEADER = "X-Trace-Id"


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Kept strictly UUID so it can double as an Action's trace_id
        # (11.3 event envelope) without a separate free-text vs. typed-id
        # split — a client-supplied non-UUID value is replaced, not rejected.
        client_supplied = request.headers.get(TRACE_ID_HEADER)
        try:
            trace_id = str(uuid.UUID(client_supplied)) if client_supplied else str(uuid.uuid4())
        except ValueError:
            trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
