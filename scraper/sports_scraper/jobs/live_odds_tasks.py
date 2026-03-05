"""Live odds polling tasks.

Fetches in-game odds from The Odds API and writes to Redis (ephemeral).
Also captures closing lines when games transition to LIVE.

Dispatched by the live_orchestrator_tick task at sport-appropriate cadences.
"""

from __future__ import annotations

from datetime import UTC, datetime

from celery import shared_task

from ..db import db_models, get_session
from ..logging import logger
from ..utils.redis_lock import LOCK_TIMEOUT_10MIN, acquire_redis_lock, release_redis_lock


@shared_task(name="poll_live_odds_mainline")
def poll_live_odds_mainline(league_code: str, game_ids: list[int]) -> dict:
    """Fetch mainline live odds for a league and fan out to Redis per game.

    Uses league-batched fetch from The Odds API (single API call returns
    odds for all live games in the league).
    """
    from ..config import settings
    from ..live_odds.closing_lines import capture_closing_lines
    from ..live_odds.redis_store import write_live_snapshot
    from ..odds.client import MARKET_TYPES, OddsAPIClient
    from ..utils.provider_request import provider_request

    lock_key = f"lock:live_odds_mainline:{league_code}"
    lock_token = acquire_redis_lock(lock_key, timeout=LOCK_TIMEOUT_10MIN)
    if not lock_token:
        return {"skipped": True, "reason": "locked"}

    try:
        client = OddsAPIClient()
        sport_key = client._sport_key(league_code)
        if not sport_key or not settings.odds_api_key:
            return {"skipped": True, "reason": "no_sport_key_or_api_key"}

        # Build game_id -> external mapping for matching
        game_id_set = set(game_ids)
        game_info: dict[int, dict] = {}
        with get_session() as session:
            games = (
                session.query(db_models.SportsGame)
                .filter(db_models.SportsGame.id.in_(game_id_set))
                .all()
            )
            for g in games:
                game_info[g.id] = {
                    "status": g.status,
                    "external_ids": g.external_ids or {},
                }

        # Ensure closing lines captured for games transitioning to live
        for gid, info in game_info.items():
            if info["status"] == "live":
                try:
                    capture_closing_lines(gid, league_code)
                except Exception as exc:
                    logger.warning(
                        "closing_lines_capture_error",
                        game_id=gid,
                        error=str(exc),
                    )

        # Fetch live odds (league-batched — single API call)
        regions = ",".join(settings.odds_config.regions)
        params = {
            "apiKey": settings.odds_api_key,
            "regions": regions,
            "markets": ",".join(MARKET_TYPES.keys()),
            "oddsFormat": "american",
        }

        response = provider_request(
            client.client,
            "GET",
            f"/sports/{sport_key}/odds",
            provider="the-odds-api",
            endpoint="live_odds",
            league=league_code,
            qps_budget=1.0,
            qps_burst=3,
            params=params,
        )

        if response is None or response.status_code != 200:
            status = response.status_code if response else "skipped"
            return {"status": str(status), "league": league_code}

        events = response.json()
        if not isinstance(events, list):
            return {"status": "empty", "league": league_code}

        # Parse and write to Redis per game
        odds_written = 0
        rate_remaining = None
        try:
            rate_remaining = int(response.headers.get("x-requests-remaining", ""))
        except (ValueError, TypeError):
            pass

        for event in events:
            event_id = event.get("id", "")

            # Match event to our game_id via odds_api_event_id
            matched_game_id = None
            for gid, info in game_info.items():
                if info["external_ids"].get("odds_api_event_id") == event_id:
                    matched_game_id = gid
                    break

            if matched_game_id is None:
                continue

            # Extract selections per market
            for bookmaker in event.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    mkt_key = MARKET_TYPES.get(market.get("key", ""))
                    if not mkt_key:
                        continue

                    selections = []
                    for outcome in market.get("outcomes", []):
                        sel = {
                            "selection": outcome.get("name", ""),
                            "line": outcome.get("point"),
                            "price": outcome.get("price"),
                        }
                        selections.append(sel)

                    if selections:
                        write_live_snapshot(
                            league=league_code,
                            game_id=matched_game_id,
                            market_key=mkt_key,
                            selections=selections,
                            provider=bookmaker.get("title", "unknown"),
                            rate_remaining=rate_remaining,
                        )
                        odds_written += 1

        logger.info(
            "poll_live_odds_mainline_complete",
            league=league_code,
            events=len(events),
            odds_written=odds_written,
        )

        return {
            "league": league_code,
            "events": len(events),
            "odds_written": odds_written,
        }

    finally:
        release_redis_lock(lock_key, lock_token)


@shared_task(name="poll_live_odds_props")
def poll_live_odds_props(league_code: str, game_ids: list[int]) -> dict:
    """Fetch live prop odds per event and write to Redis.

    Iterates events (per-game API calls). Capped at 30-60s cadence
    by the orchestrator.
    """
    from ..config import settings
    from ..live_odds.redis_store import write_live_snapshot
    from ..odds.client import OddsAPIClient, PROP_MARKETS
    from ..utils.provider_request import provider_request

    lock_key = f"lock:live_odds_props:{league_code}"
    lock_token = acquire_redis_lock(lock_key, timeout=LOCK_TIMEOUT_10MIN)
    if not lock_token:
        return {"skipped": True, "reason": "locked"}

    try:
        client = OddsAPIClient()
        sport_key = client._sport_key(league_code)
        if not sport_key or not settings.odds_api_key:
            return {"skipped": True, "reason": "no_sport_key_or_api_key"}

        # Get event IDs for our live games
        with get_session() as session:
            games = (
                session.query(db_models.SportsGame)
                .filter(
                    db_models.SportsGame.id.in_(game_ids),
                    db_models.SportsGame.status.in_(["live", "pregame"]),
                )
                .all()
            )

        events_processed = 0
        props_written = 0
        prop_markets = PROP_MARKETS.get(league_code.upper(), [])

        for game in games:
            event_id = (game.external_ids or {}).get("odds_api_event_id")
            if not event_id:
                continue

            # Check credit safety
            if client.should_abort_props:
                logger.warning("live_props_aborted_credits", league=league_code)
                break

            regions = ",".join(settings.odds_config.regions)
            params = {
                "apiKey": settings.odds_api_key,
                "regions": regions,
                "markets": ",".join(prop_markets),
                "oddsFormat": "american",
            }

            response = provider_request(
                client.client,
                "GET",
                f"/sports/{sport_key}/events/{event_id}/odds",
                provider="the-odds-api",
                endpoint="live_props",
                league=league_code,
                game_id=game.id,
                qps_budget=0.5,
                qps_burst=2,
                params=params,
            )

            if response is None or response.status_code != 200:
                continue

            client._track_credits(response)
            payload = response.json()

            for bookmaker in payload.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    mkt_key = market.get("key", "")
                    selections = [
                        {
                            "selection": o.get("name", ""),
                            "line": o.get("point"),
                            "price": o.get("price"),
                            "description": o.get("description"),
                        }
                        for o in market.get("outcomes", [])
                    ]
                    if selections:
                        write_live_snapshot(
                            league=league_code,
                            game_id=game.id,
                            market_key=mkt_key,
                            selections=selections,
                            provider=bookmaker.get("title", "unknown"),
                        )
                        props_written += 1

            events_processed += 1

        logger.info(
            "poll_live_odds_props_complete",
            league=league_code,
            events_processed=events_processed,
            props_written=props_written,
        )

        return {
            "league": league_code,
            "events_processed": events_processed,
            "props_written": props_written,
        }

    finally:
        release_redis_lock(lock_key, lock_token)
