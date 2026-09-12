"""NFR-OBS-001 / 6.3 stack decision ("OpenTelemetry, Prometheus"): a
/metrics endpoint previously didn't exist at all — no prometheus-client
dependency, no route, nothing. Proves the real thing, not just that the
route exists: a request to another endpoint actually increments a real
Prometheus counter that then shows up in /metrics' own output.
"""

from httpx import ASGITransport, AsyncClient

from doda.main import app


async def test_metrics_endpoint_reflects_a_real_request() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/v1/healthz")
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'http_requests_total{handler="/v1/healthz",method="GET",status="2xx"}' in response.text
