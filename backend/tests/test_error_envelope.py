"""11.2's error envelope ("code, xavfsiz message, trace_id, retryable,
field_errors") is only actually guaranteed for the specific exception types
`register_exception_handlers` knows about — anything else used to fall
through to FastAPI/Starlette's own default 500 body, a different,
undocumented shape, with no server-side log line tying it back to the
client-visible trace_id. This is the regression test for the catch-all
handler that closes that gap.
"""

from httpx import ASGITransport, AsyncClient

from doda.main import app


async def test_an_unexpected_exception_still_returns_the_shared_envelope() -> None:
    @app.get("/v1/__test_unhandled_exception")
    async def _boom() -> None:
        raise RuntimeError("deliberately unhandled, for this test only")

    try:
        # raise_app_exceptions=False: Starlette's ServerErrorMiddleware (which
        # runs our registered `Exception` handler) sends the real response
        # and then deliberately re-raises the original exception too, so a
        # real ASGI server (uvicorn) still logs/surfaces it after already
        # answering the client — httpx's default strict mode treats that
        # re-raise as a test failure instead of inspecting the response that
        # was already sent, which is the opposite of what an actual client
        # over the network would ever observe.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/__test_unhandled_exception")
    finally:
        # Routes added directly to app.router (bypassing include_router)
        # aren't scoped to a test client — remove it so later tests never
        # see this throwaway endpoint.
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/v1/__test_unhandled_exception"
        ]

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["retryable"] is True
    assert body["field_errors"] == {}
    # Real trace_id, not a placeholder — must match the response header
    # TraceIdMiddleware sets for every request, including failed ones.
    assert body["trace_id"] == response.headers["X-Trace-Id"]
