"""Namespace compliance test for ISSUE-009.

Enforces the consumer/admin router namespace split:
  - Consumer endpoints must live under /api/v1/.
  - Admin endpoints must live under /api/admin/.
  - Infra/platform endpoints are on a small, documented exempt list.
  - Legacy prefixes pending migration are frozen and must not grow.
"""

from __future__ import annotations

from main import app

ALLOWED_PREFIXES: tuple[str, ...] = ("/api/v1/", "/api/admin/")

EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
    }
)

LEGACY_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/auth",
    "/api/analytics/",
    "/api/fairbet/",
    "/api/golf/",
    "/api/model-odds/",
    "/api/simulator/",
    "/api/social/",
    "/v1/ws",
    "/v1/sse",
    "/v1/realtime/",
)


def _is_allowed(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return True
    return any(path.startswith(p) for p in ALLOWED_PREFIXES)


def _is_legacy(path: str) -> bool:
    return any(path.startswith(p) for p in LEGACY_EXEMPT_PREFIXES)


def test_no_new_namespace_violations() -> None:
    """Every registered route must be compliant, exempt, or grandfathered."""
    violations: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        if _is_allowed(path) or _is_legacy(path):
            continue
        violations.append(path)

    assert not violations, (
        "Routes outside /api/v1/ or /api/admin/ namespaces:\n  - "
        + "\n  - ".join(sorted(set(violations)))
    )


def test_no_router_mixes_consumer_and_admin() -> None:
    """No single route path may have both consumer (v1) and admin tags."""
    for route in app.routes:
        path = getattr(route, "path", None)
        tags = set(getattr(route, "tags", []) or [])
        if not isinstance(path, str):
            continue
        if "v1" in tags and "admin" in tags:
            raise AssertionError(
                f"Route {path} mixes v1 (consumer) and admin tags"
            )
        if path.startswith("/api/v1/") and "admin" in tags:
            raise AssertionError(
                f"Consumer route {path} is tagged as admin"
            )
        if path.startswith("/api/admin/") and "v1" in tags:
            raise AssertionError(
                f"Admin route {path} is tagged as v1 consumer"
            )


def test_legacy_exempt_list_is_frozen() -> None:
    """Guard against silently growing the legacy exempt list.

    If this count changes, update it intentionally alongside a migration plan.
    """
    expected_legacy_prefixes = 10
    assert len(LEGACY_EXEMPT_PREFIXES) == expected_legacy_prefixes, (
        "LEGACY_EXEMPT_PREFIXES changed. Either migrate the route under "
        "/api/v1/ or /api/admin/, or update this test with a linked issue."
    )
