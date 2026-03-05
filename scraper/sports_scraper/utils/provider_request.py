"""Enhanced HTTP request wrapper for provider API calls.

Features:
- Token bucket rate limiting per provider
- 429 / Retry-After handling with dynamic backoff
- Structured logging per request
- QPS budget enforcement
- Provider metrics tracking
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import httpx

from ..logging import logger

# ---------------------------------------------------------------------------
# Token bucket rate limiter
# ---------------------------------------------------------------------------


class TokenBucket:
    """Thread-safe token bucket for QPS enforcement."""

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate          # tokens per second
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 5.0) -> bool:
        """Block until a token is available or timeout expires."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.05, deadline - time.monotonic()))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now


# ---------------------------------------------------------------------------
# Per-provider metrics
# ---------------------------------------------------------------------------


@dataclass
class ProviderMetrics:
    """Accumulated metrics for a single provider."""

    requests_total: int = 0
    rate_limited_total: int = 0
    errors_total: int = 0
    last_backoff_until: float = 0.0
    last_remaining: int | None = None
    last_reset: str | None = None
    _request_log: list[dict] = field(default_factory=list)

    def record_request(self, entry: dict) -> None:
        self.requests_total += 1
        self._request_log.append(entry)
        # Keep last 200 entries
        if len(self._request_log) > 200:
            self._request_log = self._request_log[-100:]

    def summary(self) -> dict:
        return {
            "requests_total": self.requests_total,
            "rate_limited_total": self.rate_limited_total,
            "errors_total": self.errors_total,
            "backoff_active": time.monotonic() < self.last_backoff_until,
            "last_remaining": self.last_remaining,
        }


# ---------------------------------------------------------------------------
# Provider request wrapper
# ---------------------------------------------------------------------------

# Global metrics registry
_metrics: dict[str, ProviderMetrics] = {}
_metrics_lock = threading.Lock()

# Global buckets registry
_buckets: dict[str, TokenBucket] = {}
_buckets_lock = threading.Lock()

# 60-second summary state
_last_summary_time: float = 0.0
_summary_lock = threading.Lock()


def _get_metrics(provider: str) -> ProviderMetrics:
    with _metrics_lock:
        if provider not in _metrics:
            _metrics[provider] = ProviderMetrics()
        return _metrics[provider]


def _get_bucket(provider: str, qps: float, burst: int) -> TokenBucket:
    with _buckets_lock:
        if provider not in _buckets:
            _buckets[provider] = TokenBucket(rate=qps, capacity=burst)
        return _buckets[provider]


def get_provider_metrics(provider: str | None = None) -> dict:
    """Return metrics for one or all providers."""
    with _metrics_lock:
        if provider:
            m = _metrics.get(provider)
            return m.summary() if m else {}
        return {k: v.summary() for k, v in _metrics.items()}


def provider_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    provider: str,
    endpoint: str = "",
    league: str = "",
    game_id: str | int = "",
    qps_budget: float = 1.0,
    qps_burst: int = 3,
    params: dict | None = None,
    **kwargs,
) -> httpx.Response | None:
    """Make an HTTP request with rate limiting, backoff, and structured logging.

    Returns None if the request was skipped due to rate limiting / backoff.
    Raises on non-rate-limit HTTP errors.
    """
    metrics = _get_metrics(provider)
    bucket = _get_bucket(provider, qps_budget, qps_burst)

    # Check active backoff
    now = time.monotonic()
    if now < metrics.last_backoff_until:
        remaining_backoff = metrics.last_backoff_until - now
        logger.info(
            "provider_request_skipped",
            provider=provider,
            endpoint=endpoint,
            reason="backoff_active",
            backoff_remaining_s=round(remaining_backoff, 1),
        )
        return None

    # Acquire token from rate limiter
    if not bucket.acquire(timeout=5.0):
        logger.warning(
            "provider_request_skipped",
            provider=provider,
            endpoint=endpoint,
            reason="qps_budget_exhausted",
        )
        return None

    t0 = time.monotonic()
    response: httpx.Response | None = None
    status_code = 0
    try:
        response = client.request(method, url, params=params, **kwargs)
        status_code = response.status_code
    except httpx.TimeoutException:
        metrics.errors_total += 1
        logger.warning(
            "provider_request_timeout",
            provider=provider,
            endpoint=endpoint,
            league=league,
        )
        return None
    except Exception as exc:
        metrics.errors_total += 1
        logger.warning(
            "provider_request_error",
            provider=provider,
            endpoint=endpoint,
            error=str(exc),
        )
        raise

    duration_ms = round((time.monotonic() - t0) * 1000, 1)

    # Parse rate limit headers
    remaining = _parse_int_header(response, "x-requests-remaining")
    reset = response.headers.get("x-requests-reset")
    retry_after = _parse_int_header(response, "retry-after")

    if remaining is not None:
        metrics.last_remaining = remaining
    if reset:
        metrics.last_reset = reset

    # Log entry
    log_entry = {
        "type": "provider_request",
        "provider": provider,
        "endpoint": endpoint,
        "league": league,
        "game_id": str(game_id) if game_id else "",
        "status_code": status_code,
        "duration_ms": duration_ms,
        "remaining": remaining,
        "reset": reset,
        "retry_after": retry_after,
        "response_bytes": len(response.content) if response else 0,
    }
    metrics.record_request(log_entry)

    logger.info("provider_request", **log_entry)

    # Handle 429
    if status_code == 429:
        metrics.rate_limited_total += 1
        backoff_seconds = retry_after if retry_after and retry_after > 0 else 60
        metrics.last_backoff_until = time.monotonic() + backoff_seconds
        logger.warning(
            "provider_rate_limited",
            provider=provider,
            endpoint=endpoint,
            retry_after=retry_after,
            backoff_seconds=backoff_seconds,
        )
        return None

    # Emit 60-second summary if due
    _maybe_emit_summary()

    return response


def _parse_int_header(response: httpx.Response, header: str) -> int | None:
    val = response.headers.get(header)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return None


def _maybe_emit_summary() -> None:
    """Emit a summary log every 60 seconds."""
    global _last_summary_time
    now = time.monotonic()

    with _summary_lock:
        if now - _last_summary_time < 60:
            return
        _last_summary_time = now

    summaries = get_provider_metrics()
    if summaries:
        logger.info("provider_summary_60s", providers=summaries)
