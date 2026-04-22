#!/usr/bin/env python3
"""Lint FastAPI route registrations for consumer/admin namespace compliance.

Policy (ISSUE-009):
  - Consumer endpoints must live under /api/v1/.
  - Admin endpoints must live under /api/admin/.
  - Infra/platform endpoints have a narrow, documented exempt list below.

Any route whose path is not in one of the two namespaces, and not in the
exempt allowlist, is a violation. The exempt list is frozen: adding new
entries requires explicit justification in the PR and issue link.

Exit 0 on success, 1 on violations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "api"
sys.path.insert(0, str(API_DIR))

# Allowed namespace prefixes for new routes.
ALLOWED_PREFIXES: tuple[str, ...] = ("/api/v1/", "/api/admin/")

# Infra/platform endpoints exempt from the namespace rule.
# Adding new entries requires a linked follow-up issue.
EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
        # Kubernetes liveness/readiness probes and Prometheus scrape target.
        # Must stay at root-level unversioned paths per ops conventions.
        "/health",
        "/ready",
        "/metrics",
        # Stripe webhook — URL is configured in the Stripe dashboard and
        # signed by Stripe; it's not a consumer or admin surface.
        "/api/webhooks/stripe",
        # Prospect-facing onboarding flow — public (no API key), rate-limited
        # per-IP. Pre-signup endpoints, not a consumer (/api/v1/) or admin
        # (/api/admin/) surface. See onboarding router for details.
        "/api/onboarding/club-claims",
        "/api/onboarding/claim",
        "/api/onboarding/session/{session_token}",
    }
)

# Legacy prefixes pending migration to /api/v1/ in follow-up issues.
# These must not grow. Any new route outside ALLOWED_PREFIXES fails lint.
LEGACY_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/auth",             # pending: migrate to /api/v1/auth
    "/api/analytics/",   # pending: split consumer reads vs admin mutations
    "/api/fairbet/",     # pending: migrate to /api/v1/fairbet
    "/api/golf/",        # pending: migrate to /api/v1/golf
    "/api/model-odds/",  # pending: migrate to /api/v1/model-odds
    "/api/simulator/",   # pending: migrate to /api/v1/simulator
    "/api/social/",      # pending: migrate to /api/v1/social
    "/v1/ws",            # pending: migrate to /api/v1/ws
    "/v1/sse",           # pending: migrate to /api/v1/sse
    "/v1/realtime/",     # pending: migrate to /api/v1/realtime/
)


def _is_allowed(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return True
    if any(path.startswith(p) for p in ALLOWED_PREFIXES):
        return True
    return False


def _is_legacy(path: str) -> bool:
    return any(path.startswith(p) for p in LEGACY_EXEMPT_PREFIXES)


def _load_app():
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    from main import app  # type: ignore

    return app


def main() -> int:
    app = _load_app()

    violations: list[str] = []
    legacy_hits: list[str] = []
    compliant = 0

    for route in app.routes:
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        if _is_allowed(path):
            compliant += 1
            continue
        if _is_legacy(path):
            legacy_hits.append(path)
            continue
        violations.append(path)

    print(f"Routes scanned: {len(app.routes)}")
    print(f"  compliant (/api/v1/ or /api/admin/ or infra): {compliant}")
    print(f"  legacy (grandfathered, pending migration): {len(legacy_hits)}")
    print(f"  violations: {len(violations)}")

    if violations:
        print("\nERROR: routes outside allowed namespaces:")
        for p in sorted(set(violations)):
            print(f"  - {p}")
        print(
            "\nConsumer routes must mount under /api/v1/, admin under /api/admin/.\n"
            "If this is an infra/platform endpoint, add it to EXEMPT_PATHS with\n"
            "justification in the PR."
        )
        return 1

    print("OK: no new namespace violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
