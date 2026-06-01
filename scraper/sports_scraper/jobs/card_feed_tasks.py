"""Materialized card-feed refresh tasks."""

from __future__ import annotations

import httpx
from celery import shared_task

from ..config import settings
from ..logging import logger


@shared_task(name="refresh_card_feeds")
def refresh_card_feeds(
    lookback_hours: int = 96,
    lookahead_hours: int = 48,
    force: bool = False,
) -> dict:
    """Ask the API to refresh materialized card feeds for the active data window."""
    url = f"{settings.api_internal_url.rstrip('/')}/api/admin/sports/card-feeds/refresh"
    headers: dict[str, str] = {}
    if settings.api_key:
        headers["X-API-Key"] = settings.api_key
    params = {
        "lookbackHours": lookback_hours,
        "lookaheadHours": lookahead_hours,
        "force": str(force).lower(),
    }
    try:
        response = httpx.post(url, params=params, headers=headers, timeout=120.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning(
            "card_feed_refresh_failed",
            url=url,
            lookback_hours=lookback_hours,
            lookahead_hours=lookahead_hours,
            force=force,
            error=str(exc),
            exc_info=True,
        )
        raise

    logger.info(
        "card_feed_refresh_complete",
        scanned_games=payload.get("scannedGames"),
        generated=payload.get("generated"),
        skipped_current=payload.get("skippedCurrent"),
        failed=payload.get("failed"),
    )
    return payload
