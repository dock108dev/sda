from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sports_scraper import celery_app as celery_module
from sports_scraper.jobs.card_feed_tasks import refresh_card_feeds
from sports_scraper.jobs.polling_tasks import _enqueue_card_feed_refresh


def test_refresh_card_feeds_calls_admin_refresh_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _post(url, *, params, headers, timeout):
        captured.update(
            {
                "url": url,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "scannedGames": 8,
                "generated": 6,
                "skippedCurrent": 2,
                "failed": 0,
            },
        )

    monkeypatch.setattr(
        "sports_scraper.jobs.card_feed_tasks.settings.api_internal_url",
        "http://api:8000/",
    )
    monkeypatch.setattr("sports_scraper.jobs.card_feed_tasks.settings.api_key", "admin-key")
    monkeypatch.setattr("sports_scraper.jobs.card_feed_tasks.httpx.post", _post)

    result = refresh_card_feeds.run(lookback_hours=72, lookahead_hours=72, force=True)

    assert result["generated"] == 6
    assert captured == {
        "url": "http://api:8000/api/admin/sports/card-feeds/refresh",
        "params": {
            "lookbackHours": 72,
            "lookaheadHours": 72,
            "force": "true",
        },
        "headers": {"X-API-Key": "admin-key"},
        "timeout": 120.0,
    }


def test_refresh_card_feeds_raises_on_admin_endpoint_failure(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "sports_scraper.jobs.card_feed_tasks.httpx.post",
        lambda *args, **kwargs: _Response(),
    )

    with pytest.raises(RuntimeError, match="boom"):
        refresh_card_feeds.run()


def test_pbp_update_enqueues_card_feed_refresh(monkeypatch) -> None:
    celery_app = MagicMock()
    monkeypatch.setattr(celery_module, "app", celery_app)
    monkeypatch.setattr(celery_module, "DEFAULT_QUEUE", "sports-scraper")

    _enqueue_card_feed_refresh()

    celery_app.send_task.assert_called_once_with(
        "refresh_card_feeds",
        kwargs={"lookback_hours": 96, "lookahead_hours": 48, "force": False},
        queue="sports-scraper",
        routing_key="sports-scraper",
    )
