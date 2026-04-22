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
