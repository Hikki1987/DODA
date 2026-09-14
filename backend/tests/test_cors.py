"""CORS is required for the Next.js frontend (a separate origin) to call
this API from the browser at all — without it, every fetch() call would
be silently blocked regardless of the Authorization header being correct.
No DB needed: the browser's preflight and the actual response headers are
added by middleware before any route handler runs.
"""

from httpx import ASGITransport, AsyncClient

from doda.main import app


async def test_configured_frontend_origin_is_allowed() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/healthz", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_an_unconfigured_origin_is_not_echoed_back() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/healthz", headers={"Origin": "https://evil.example.com"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_preflight_for_a_real_request_allows_authorization_header() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/v1/me/workspaces",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
