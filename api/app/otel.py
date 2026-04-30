"""OpenTelemetry SDK initialization for the API process.

Call configure_telemetry() before FastAPI app creation and instrument_fastapi()
after. All functions are no-ops when OTEL_EXPORTER_OTLP_ENDPOINT is unset so
local dev works without a collector running (``otel_disabled`` log at INFO).

Application counters and histograms exposed at ``GET /metrics`` use
``prometheus_client`` separately from OTLP export; both can be enabled together.
"""
from __future__ import annotations

import logging
import os

_logger = logging.getLogger(__name__)
_configured = False


def configure_telemetry(service_name: str, environment: str) -> None:
    """Initialize OTel trace + metrics providers with OTLP gRPC export.

    Also instruments the Celery client so HTTP→Celery trace context propagates.
    """
    global _configured
    if _configured:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        _logger.info("otel_disabled — OTEL_EXPORTER_OTLP_ENDPOINT not set, skipping OTel setup")
        _configured = True
        return

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": environment,
    })

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint),
        export_interval_millis=15_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

    # Instrument the Celery client so apply_async injects W3C traceparent headers,
    # making each dispatched task a child span of the originating HTTP request.
    CeleryInstrumentor().instrument()

    _configured = True
    _logger.info("otel_configured", extra={"service": service_name, "endpoint": endpoint})


def instrument_fastapi(app) -> None:
    """Attach OTel spans to every FastAPI route. Call after app creation.

    Emits route template, HTTP method, and status code as span attributes.
    """
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""):
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)


def instrument_sqlalchemy_engine(engine) -> None:
    """Instrument an AsyncEngine so DB queries appear as child spans.

    Pass the AsyncEngine returned by create_async_engine; the instrumentor
    extracts the underlying sync engine automatically.
    """
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""):
        return
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
