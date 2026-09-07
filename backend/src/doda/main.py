"""FastAPI application entrypoint — Experience layer (6.1).

This wires cross-cutting concerns (observability, error envelope) and
mounts feature routers. It must not contain domain or authorization logic
(6.2: "Web qatlami to'g'ridan-to'g'ri bazaga yoki tashqi providerga
ulanmaydi").
"""

import logging

import structlog
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider

from doda.api.health import router as health_router
from doda.config import get_settings


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
    )


def _configure_tracing(service_name: str) -> None:
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    trace.set_tracer_provider(provider)


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging()
    _configure_tracing(settings.otel_service_name)

    app = FastAPI(title="DODA API", version="0.1.0")
    app.include_router(health_router, prefix="/v1")
    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
