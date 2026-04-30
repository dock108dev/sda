"""Tests for TRUST_FORWARDED_ORIGIN gating on admin origin resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.dependencies.roles import _is_admin_origin


def _request(
    *,
    origin: str | None = None,
    forwarded: str | None = None,
    referer: str | None = None,
) -> MagicMock:
    headers: dict[str, str] = {}
    if origin:
        headers["origin"] = origin
    if forwarded:
        headers["x-forwarded-origin"] = forwarded
    if referer:
        headers["referer"] = referer
    req = MagicMock()

    def _get(name: str, default: str | None = None) -> str | None:
        return headers.get(name, default)

    req.headers.get = _get
    return req


def test_forwarded_origin_ignored_by_default() -> None:
    req = _request(forwarded="http://localhost:3000")
    with patch(
        "app.dependencies.roles.settings",
        MagicMock(admin_origins=["http://localhost:3000"], trust_forwarded_origin=False),
    ):
        assert _is_admin_origin(req) is False


def test_forwarded_origin_honored_when_trusted() -> None:
    req = _request(forwarded="http://localhost:3000")
    with patch(
        "app.dependencies.roles.settings",
        MagicMock(admin_origins=["http://localhost:3000"], trust_forwarded_origin=True),
    ):
        assert _is_admin_origin(req) is True


def test_origin_always_evaluated() -> None:
    req = _request(origin="http://localhost:3000")
    with patch(
        "app.dependencies.roles.settings",
        MagicMock(admin_origins=["http://localhost:3000"], trust_forwarded_origin=False),
    ):
        assert _is_admin_origin(req) is True
