"""Tests for ISSUE-025 security hardening.

- HTTP response header middleware
- bleach-based free-text sanitization
- Pydantic-validator wiring for club name and pool name/notes
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security_headers import SecurityHeadersMiddleware
from app.utils.sanitize import sanitize_text


# ---------------------------------------------------------------------------
# Security-header middleware
# ---------------------------------------------------------------------------


def _app_with_headers() -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def _ping() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


class TestSecurityHeaders:
    def test_all_baseline_headers_present(self) -> None:
        client = _app_with_headers()
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.headers["content-security-policy"].startswith("default-src 'self'")
        assert "base-uri 'self'" in resp.headers["content-security-policy"]
        assert "object-src 'none'" in resp.headers["content-security-policy"]
        assert (
            resp.headers["strict-transport-security"]
            == "max-age=31536000; includeSubDomains"
        )
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["referrer-policy"] == "same-origin"
        assert (
            resp.headers["permissions-policy"]
            == "camera=(), microphone=(), geolocation=()"
        )

    def test_headers_on_404(self) -> None:
        """Error responses must also carry the hardening headers."""
        client = _app_with_headers()
        resp = client.get("/does-not-exist")
        assert resp.status_code == 404
        for h in (
            "content-security-policy",
            "strict-transport-security",
            "x-frame-options",
            "x-content-type-options",
            "referrer-policy",
            "permissions-policy",
        ):
            assert h in resp.headers, f"missing {h} on 404 response"

    def test_preserves_existing_header(self) -> None:
        """If a downstream handler already sets a CSP, the middleware must
        not overwrite it."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/custom")
        async def _custom() -> Any:
            from starlette.responses import JSONResponse

            return JSONResponse(
                {"ok": True},
                headers={"content-security-policy": "default-src 'none'"},
            )

        client = TestClient(app)
        resp = client.get("/custom")
        assert resp.headers["content-security-policy"] == "default-src 'none'"
        # Other hardening headers still injected
        assert resp.headers["x-frame-options"] == "DENY"


# ---------------------------------------------------------------------------
# Sanitization helper
# ---------------------------------------------------------------------------


class TestSanitizeText:
    def test_strips_script_tag(self) -> None:
        result = sanitize_text("<script>alert('xss')</script>Pine Valley")
        assert "<script>" not in result
        assert "</script>" not in result
        # bleach.clean with strip=True removes the tag but keeps text content
        assert "Pine Valley" in result

    def test_strips_all_tags(self) -> None:
        assert sanitize_text("<b>bold</b><img src=x>") == "bold"

    def test_plain_text_unchanged(self) -> None:
        assert sanitize_text("Pine Valley GC") == "Pine Valley GC"

    def test_non_string_passthrough(self) -> None:
        assert sanitize_text(None) is None
        assert sanitize_text(42) == 42


# ---------------------------------------------------------------------------
# ClubClaimRequest / PoolCreateRequest validator wiring (integration-style)
# ---------------------------------------------------------------------------


class TestClubClaimSanitization:
    def test_script_tag_stripped_before_orm_write(self) -> None:
        """POST /api/onboarding/club-claims: <script> in clubName is stripped
        before the ClubClaim ORM row is built.

        Satisfies the ISSUE-025 AC: "club name containing <script> tag stores
        sanitized value, never raw HTML".
        """
        from app.db import get_db
        from app.db.onboarding import ClubClaim
        from app.middleware.rate_limit import RateLimitMiddleware
        from app.routers.onboarding import router

        captured: list[ClubClaim] = []

        class _Sess:
            committed = False

            def add(self, obj: Any) -> None:
                captured.append(obj)

            async def flush(self) -> None:
                from datetime import UTC, datetime

                for o in captured:
                    if getattr(o, "received_at", None) is None:
                        o.received_at = datetime.now(UTC)

            async def commit(self) -> None:
                self.committed = True

            async def refresh(self, obj: Any) -> None:
                pass

            async def close(self) -> None:
                pass

        sess = _Sess()

        async def _override_db():
            yield sess

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)
        app.dependency_overrides[get_db] = _override_db
        app.include_router(router)
        client = TestClient(app)

        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json={
                    "clubName": "<script>alert(1)</script>Pine Valley",
                    "contactEmail": "pro@pv.example",
                    "notes": "<img src=x onerror=1>Welcome",
                },
            )

        assert resp.status_code == 201, resp.text
        assert len(captured) == 1
        row = captured[0]
        # Raw HTML must not survive into the ORM payload.
        assert "<script>" not in row.club_name
        assert "</script>" not in row.club_name
        assert "<img" not in row.notes
        assert "Pine Valley" in row.club_name
        assert "Welcome" in row.notes


class TestPoolCreateSanitization:
    def test_pool_name_and_notes_stripped(self) -> None:
        from app.routers.golf.pools_helpers import (
            PoolCreateRequest,
            PoolUpdateRequest,
        )

        req = PoolCreateRequest(
            code="abc",
            name="<script>bad</script>Member-Guest",
            club_code="rvcc",
            tournament_id=1,
            notes="<b>bold</b>desc",
        )
        assert "<script>" not in req.name
        assert "Member-Guest" in req.name
        assert "<b>" not in (req.notes or "")
        assert "bolddesc" == req.notes

        update = PoolUpdateRequest(
            name="<iframe>x</iframe>Updated",
            notes="<a href=# onclick=1>ok</a>",
        )
        assert "<iframe>" not in (update.name or "")
        assert "Updated" in (update.name or "")
        assert "<a" not in (update.notes or "")
