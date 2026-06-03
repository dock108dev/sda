from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "refresh_card_feeds.py"
SPEC = importlib.util.spec_from_file_location("refresh_card_feeds", SCRIPT_PATH)
assert SPEC and SPEC.loader
refresher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresher)


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "scannedGames": 3,
                "eligibleGames": 2,
                "generated": 2,
                "skippedCurrent": 0,
                "failed": 0,
                "errors": [],
            }
        ).encode("utf-8")


def test_refresh_script_posts_admin_endpoint_with_admin_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=admin-key\nCONSUMER_API_KEY=consumer-key\n", encoding="utf-8")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["method"] = request.get_method()
        return _Response()

    monkeypatch.setattr(refresher.urllib.request, "urlopen", fake_urlopen)
    args = SimpleNamespace(
        base_url="http://localhost:8000",
        api_key=None,
        env_file=str(env_file),
        lookback_hours=72,
        lookahead_hours=72,
        force=False,
    )

    payload = refresher._request_refresh(args)

    assert payload["generated"] == 2
    assert captured["method"] == "POST"
    assert "/api/admin/sports/card-feeds/refresh?" in captured["url"]
    assert "lookbackHours=72" in captured["url"]
    assert captured["headers"]["X-api-key"] == "admin-key"
