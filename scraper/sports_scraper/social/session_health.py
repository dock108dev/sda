"""Playwright session health probe for X/Twitter authentication.

Runs a lightweight DOM check against x.com to verify auth cookies are still
valid. Results are persisted to Redis so the admin dashboard can display them
and the circuit breaker state is visible within seconds of a probe run.

Redis keys:
  playwright:session:health               — JSON health snapshot, 1h TTL
  playwright:session:circuit_open         — "1" when circuit is tripped, 1h TTL
  playwright:session:consecutive_failures — int counter reset on success, 1h TTL

Circuit breaker trips after CIRCUIT_BREAKER_THRESHOLD consecutive probe failures.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from ..logging import logger

HEALTH_KEY = "playwright:session:health"
CIRCUIT_OPEN_KEY = "playwright:session:circuit_open"
CONSECUTIVE_FAILURES_KEY = "playwright:session:consecutive_failures"

# Trip the circuit breaker after this many consecutive probe failures.
CIRCUIT_BREAKER_THRESHOLD = 3

# TTL for all keys — 1 hour so a missed beat cycle doesn't immediately clear state.
_KEY_TTL_SECONDS = 60 * 60

# Hard cap for the entire browser session inside the worker thread.
_PROBE_THREAD_TIMEOUT_SECONDS = 12


@dataclass
class SessionHealthResult:
    is_valid: bool
    checked_at: str  # ISO-8601 UTC
    failure_reason: str | None = None
    auth_token_present: bool = False
    ct0_present: bool = False


def _probe_impl(auth_token: str | None, ct0: str | None) -> SessionHealthResult:
    """Run the actual Playwright check on the calling thread (no asyncio loop)."""
    from importlib.util import find_spec

    if find_spec("playwright.sync_api") is None:
        return SessionHealthResult(
            is_valid=False,
            checked_at=datetime.now(timezone.utc).isoformat(),
            failure_reason="playwright not installed",
        )

    from playwright.sync_api import sync_playwright

    checked_at = datetime.now(timezone.utc).isoformat()
    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        context.add_cookies(
            [
                {"name": "auth_token", "value": auth_token, "domain": ".x.com", "path": "/"},
                {"name": "ct0", "value": ct0, "domain": ".x.com", "path": "/"},
            ]
        )
        page = context.new_page()
        try:
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=7_000)
        except Exception as nav_exc:
            return SessionHealthResult(
                is_valid=False,
                checked_at=checked_at,
                failure_reason=f"navigation failed: {nav_exc}",
                auth_token_present=bool(auth_token),
                ct0_present=bool(ct0),
            )

        # Redirect to /login means session is dead
        if page.url and "/login" in page.url:
            return SessionHealthResult(
                is_valid=False,
                checked_at=checked_at,
                failure_reason="redirected to /login — session expired",
                auth_token_present=bool(auth_token),
                ct0_present=bool(ct0),
            )

        login_btn = page.query_selector('[data-testid="loginButton"]')
        if login_btn:
            return SessionHealthResult(
                is_valid=False,
                checked_at=checked_at,
                failure_reason="login button present — not authenticated",
                auth_token_present=bool(auth_token),
                ct0_present=bool(ct0),
            )

        home_link = page.query_selector('[data-testid="AppTabBar_Home_Link"]')
        if home_link:
            return SessionHealthResult(
                is_valid=True,
                checked_at=checked_at,
                auth_token_present=bool(auth_token),
                ct0_present=bool(ct0),
            )

        # Indeterminate — neither login button nor home nav found
        return SessionHealthResult(
            is_valid=False,
            checked_at=checked_at,
            failure_reason="indeterminate — neither login button nor home nav found",
            auth_token_present=bool(auth_token),
            ct0_present=bool(ct0),
        )
    except Exception as exc:
        return SessionHealthResult(
            is_valid=False,
            checked_at=checked_at,
            failure_reason=f"probe error: {exc}",
            auth_token_present=bool(auth_token),
            ct0_present=bool(ct0),
        )
    finally:
        try:
            browser.close() if browser else None
        except Exception:
            logger.debug("session_health_browser_close_failed", exc_info=True)
        try:
            pw.stop() if pw else None
        except Exception:
            logger.debug("session_health_pw_stop_failed", exc_info=True)


def probe_session_health(
    auth_token: str | None = None,
    ct0: str | None = None,
) -> SessionHealthResult:
    """Launch a lightweight Playwright check and return the health result.

    Runs on a dedicated thread to avoid conflicts with any asyncio loop on the
    calling thread (same pattern as PlaywrightXCollector). Hard-capped at
    _PROBE_THREAD_TIMEOUT_SECONDS so it cannot block a Celery worker slot.
    """
    resolved_token = auth_token or os.environ.get("X_AUTH_TOKEN")
    resolved_ct0 = ct0 or os.environ.get("X_CT0")

    if not resolved_token or not resolved_ct0:
        return SessionHealthResult(
            is_valid=False,
            checked_at=datetime.now(timezone.utc).isoformat(),
            failure_reason="X_AUTH_TOKEN or X_CT0 not configured",
            auth_token_present=bool(resolved_token),
            ct0_present=bool(resolved_ct0),
        )

    ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw-health")
    future = ex.submit(_probe_impl, resolved_token, resolved_ct0)
    try:
        result = future.result(timeout=_PROBE_THREAD_TIMEOUT_SECONDS)
        ex.shutdown(wait=False)
        return result
    except FutureTimeoutError:
        # Don't block on the orphaned thread — let it finish in the background.
        ex.shutdown(wait=False)
        return SessionHealthResult(
            is_valid=False,
            checked_at=datetime.now(timezone.utc).isoformat(),
            failure_reason=f"probe timed out after {_PROBE_THREAD_TIMEOUT_SECONDS}s",
            auth_token_present=bool(resolved_token),
            ct0_present=bool(resolved_ct0),
        )


def record_health(redis_client: Any, result: SessionHealthResult) -> bool:
    """Persist health result and manage the circuit breaker in Redis.

    Returns True exactly when the circuit breaker transitions from closed to
    open (i.e. the CIRCUIT_BREAKER_THRESHOLD-th consecutive failure), so the
    caller can emit a one-time alert without re-alerting on subsequent failures.
    """
    payload = json.dumps(asdict(result))
    redis_client.set(HEALTH_KEY, payload, ex=_KEY_TTL_SECONDS)

    if result.is_valid:
        redis_client.delete(CIRCUIT_OPEN_KEY)
        redis_client.delete(CONSECUTIVE_FAILURES_KEY)
        return False

    # Increment the consecutive-failure counter (atomic; creates key at 0 first).
    count = redis_client.incr(CONSECUTIVE_FAILURES_KEY)
    redis_client.expire(CONSECUTIVE_FAILURES_KEY, _KEY_TTL_SECONDS)

    if count >= CIRCUIT_BREAKER_THRESHOLD:
        redis_client.set(CIRCUIT_OPEN_KEY, "1", ex=_KEY_TTL_SECONDS)
        # Return True only on the exact transition (count == threshold) so
        # the caller alerts once rather than on every subsequent failure.
        return count == CIRCUIT_BREAKER_THRESHOLD

    return False


def get_consecutive_failures(redis_client: Any) -> int:
    """Return the current consecutive-failure count (0 if key absent)."""
    raw = redis_client.get(CONSECUTIVE_FAILURES_KEY)
    try:
        return int(raw) if raw else 0
    except (TypeError, ValueError):
        return 0


def get_cached_health(redis_client: Any) -> dict | None:
    """Return the last recorded health snapshot from Redis, or None if absent."""
    raw = redis_client.get(HEALTH_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def is_circuit_open(redis_client: Any) -> bool:
    """Return True if the session circuit breaker is currently tripped."""
    return redis_client.get(CIRCUIT_OPEN_KEY) == "1"
