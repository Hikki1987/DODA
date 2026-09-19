"""NFR-OBS-001 / 6.3 stack decision: FastAPIInstrumentor was already wired
up, but the TracerProvider had no span processor attached — spans were
created (and trace_id propagation worked) but silently discarded, never
exported anywhere, not even to stdout. Proves capture actually works now
by attaching a second, test-only span processor to the same (real, already
configured by importing doda.main) global provider and checking a real
HTTP request produces a real, finished span.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from doda.main import app  # noqa: F401 — importing doda.main is what configures the global tracer provider


async def test_a_real_request_produces_a_finished_span() -> None:
    from httpx import ASGITransport, AsyncClient

    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))  # type: ignore[attr-defined]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/v1/healthz")

    spans = exporter.get_finished_spans()
    server_spans = [s for s in spans if s.attributes and s.attributes.get("http.route") == "/v1/healthz"]
    assert server_spans, f"expected a finished span for /v1/healthz, got: {[s.name for s in spans]}"
