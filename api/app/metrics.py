"""Prometheus metrics definitions for the API.

All metrics use the default prometheus_client registry so that
generate_latest() at /metrics captures them automatically.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests by method, path, and status code",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

active_pools_total = Gauge(
    "active_pools_total",
    "Golf pools with status open, locked, or live",
)

webhook_queue_depth = Gauge(
    "webhook_queue_depth",
    "Stripe webhook events pending retry (failed, not yet dead-lettered)",
)

unhandled_exceptions_total = Counter(
    "unhandled_exceptions_total",
    "Requests that hit the global Exception handler (after other handlers)",
)

rate_limit_redis_fallback_total = Counter(
    "rate_limit_redis_fallback_total",
    "Redis rate-limit errors that fell back to in-memory limiting",
    ["tier"],
)

circuit_breaker_flush_errors_total = Counter(
    "circuit_breaker_flush_errors_total",
    "Failed attempts to persist buffered circuit-breaker trips to the database",
)

stripe_webhook_async_queued_total = Counter(
    "stripe_webhook_async_queued_total",
    "Stripe webhook handler DB errors that returned 202 and enqueued Celery retry",
)

stripe_webhook_dead_letter_total = Counter(
    "stripe_webhook_dead_letter_total",
    "Stripe webhook Celery task moved to dead letter after max retries",
)

analytics_batch_sim_serialization_failures_total = Counter(
    "analytics_batch_sim_serialization_failures_total",
    "Batch sim job rows skipped in list response due to serialization failure",
)

pipeline_stage_failures_total = Counter(
    "pipeline_stage_failures_total",
    "Narrative pipeline stage executions that ended in failure",
    ["stage"],
)
