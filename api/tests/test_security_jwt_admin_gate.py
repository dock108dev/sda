"""JWT + API key interaction for admin role (proxy hardening)."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.dependencies.roles import create_access_token, require_admin


async def _fake_verify_api_key(request: Request, api_key: str | None = None) -> str:
    request.state.api_key_verified = True
    return api_key or "test-admin-key"


def test_non_admin_jwt_cannot_pass_require_admin_with_proxy_key() -> None:
    app = FastAPI()

    @app.get(
        "/gate",
        dependencies=[Depends(_fake_verify_api_key), Depends(require_admin)],
    )
    def _gate() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(app)
    token = create_access_token(999001, "user", remember_me=False)
    resp = client.get(
        "/gate",
        headers={
            "X-API-Key": "test-admin-key",
            "Authorization": f"Bearer {token}",
        },
    )
    assert resp.status_code == 403


def test_admin_role_without_jwt_still_passes_require_admin() -> None:
    app = FastAPI()

    @app.get(
        "/gate",
        dependencies=[Depends(_fake_verify_api_key), Depends(require_admin)],
    )
    def _gate() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(app)
    resp = client.get("/gate", headers={"X-API-Key": "test-admin-key"})
    assert resp.status_code == 200
