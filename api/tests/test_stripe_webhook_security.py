"""Stripe webhook signature enforcement."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.db import get_db
from app.routers.webhooks import _verify_signature, router


def test_verify_signature_invalid_raises_http_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _verify_signature(
            b"{}",
            "t=0,v1=deadbeef",
            "whsec_" + "b" * 32,
        )
    assert exc_info.value.status_code == 400


def _app_with_db_override() -> TestClient:
    app = FastAPI()
    app.include_router(router)

    async def _fake_db() -> AsyncGenerator[AsyncMock, None]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = _fake_db
    return TestClient(app)


def test_stripe_webhook_rejects_invalid_signature() -> None:
    client = _app_with_db_override()
    with patch("app.routers.webhooks.settings") as s:
        s.stripe_webhook_secret = "whsec_" + "b" * 32
        resp = client.post(
            "/api/webhooks/stripe",
            content=b'{"id":"evt_1"}',
            headers={"stripe-signature": "t=0,v1=deadbeef"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("detail", {}).get("error") == "invalid_signature"


def test_stripe_webhook_missing_secret_returns_503() -> None:
    client = _app_with_db_override()
    with patch("app.routers.webhooks.settings") as s:
        s.stripe_webhook_secret = None
        resp = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=0,v1=x"},
        )
    assert resp.status_code == 503
