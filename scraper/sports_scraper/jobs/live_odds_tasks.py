"""Live odds polling tasks.

Fetches in-game odds from The Odds API and writes to Redis (ephemeral).
Also captures closing lines when games transition to LIVE.

Dispatched by the live_orchestrator_tick task at sport-appropriate cadences.
"""

from __future__ import annotations

from collections import defaultdict

from celery import shared_task

from ..db import db_models, get_session
from ..logging import logger
from ..utils.redis_lock import LOCK_TIMEOUT_10MIN, acquire_redis_lock, release_redis_lock


@shared_task(name="poll_live_odds_mainline")
def poll_live_odds_mainline(league_code: str, game_ids: list[int]) -> dict:
    """Fetch mainline live odds for a league and fan out to Redis per game.

    Uses league-batched fetch from The Odds API (single API call returns
    odds for all live games in the league).

    Aggregates ALL bookmakers per (game, market) into a single Redis
    snapshot so the API can compute fair-bet / +EV across books.
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
            # Pre-load team names for fallback matching
            team_ids = set()
            for g in games:
                team_ids.add(g.home_team_id)
                team_ids.add(g.away_team_id)
            team_name_map: dict[int, str] = {}
            if team_ids:
                teams = (
                    session.query(db_models.SportsTeam.id, db_models.SportsTeam.name)
                    .filter(db_models.SportsTeam.id.in_(team_ids))
                    .all()
                )
                team_name_map = {t.id: t.name for t in teams}

            for g in games:
                game_info[g.id] = {
                    "status": g.status,
                    "external_ids": g.external_ids or {},
                    "home_team_name": team_name_map.get(g.home_team_id, ""),
                    "away_team_name": team_name_map.get(g.away_team_id, ""),
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

        rate_remaining = None
        try:
            rate_remaining = int(response.headers.get("x-requests-remaining", ""))
        except (ValueError, TypeError):
            pass

        # Build event_id -> game_id lookup
        event_to_game: dict[str, int] = {}
        for gid, info in game_info.items():
            eid = info["external_ids"].get("odds_api_event_id")
            if eid:
                event_to_game[eid] = gid

        # Fallback: match events by team name for games missing odds_api_event_id
        games_without_eid = {
            gid for gid, info in game_info.items()
            if not info["external_ids"].get("odds_api_event_id")
        }
        if games_without_eid and events:
            from ..normalization import normalize_team_name

            # Build normalized name lookup: (home_norm, away_norm) -> game_id
            name_to_game: dict[tuple[str, str], int] = {}
            for gid in games_without_eid:
                info = game_info[gid]
                h_norm, _ = normalize_team_name(league_code, info["home_team_name"])
                a_norm, _ = normalize_team_name(league_code, info["away_team_name"])
                name_to_game[(h_norm.lower(), a_norm.lower())] = gid

            for event in events:
                eid = event.get("id", "")
                if eid in event_to_game:
                    continue  # Already matched
                h_name = event.get("home_team", "")
                a_name = event.get("away_team", "")
                h_norm, _ = normalize_team_name(league_code, h_name)
                a_norm, _ = normalize_team_name(league_code, a_name)
                key = (h_norm.lower(), a_norm.lower())
                matched_gid = name_to_game.get(key)
                # Also try swapped (neutral sites)
                if matched_gid is None:
                    matched_gid = name_to_game.get((a_norm.lower(), h_norm.lower()))
                if matched_gid is not None:
                    event_to_game[eid] = matched_gid
                    # Persist the event ID so future polls use fast path
                    try:
                        with get_session() as session:
                            game = session.get(db_models.SportsGame, matched_gid)
                            if game:
                                ext = dict(game.external_ids or {})
                                ext["odds_api_event_id"] = eid
                                game.external_ids = ext
                                session.commit()
                        logger.info(
                            "live_odds_event_id_backfilled",
                            game_id=matched_gid,
                            event_id=eid,
                            league=league_code,
                        )
                    except Exception as exc:
                        logger.warning(
                            "live_odds_event_id_backfill_error",
                            game_id=matched_gid,
                            error=str(exc),
                        )

        # Log match summary for debugging
        matched_count = len(event_to_game)
        unmatched_events = [
            {"id": e.get("id", ""), "home": e.get("home_team", ""), "away": e.get("away_team", "")}
            for e in events if e.get("id", "") not in event_to_game
        ]
        if unmatched_events:
            logger.warning(
                "live_odds_unmatched_events",
                league=league_code,
                matched=matched_count,
                unmatched=len(unmatched_events),
                samples=unmatched_events[:5],
                db_games=len(game_info),
                games_with_eid=len(event_to_game),
            )

        # Aggregate all bookmakers per (game_id, market_key)
        # Structure: {(game_id, market_key): {book_name: [selections]}}
        aggregated: dict[tuple[int, str], dict[str, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for event in events:
            event_id = event.get("id", "")
            matched_game_id = event_to_game.get(event_id)
            if matched_game_id is None:
                continue

            for bookmaker in event.get("bookmakers", []):
                book_name = bookmaker.get("title", "unknown")
                for market in bookmaker.get("markets", []):
                    mkt_key = MARKET_TYPES.get(market.get("key", ""))
                    if not mkt_key:
                        continue

                    selections = []
                    for outcome in market.get("outcomes", []):
                        selections.append({
                            "selection": outcome.get("name", ""),
                            "line": outcome.get("point"),
                            "price": outcome.get("price"),
                        })

                    if selections:
                        aggregated[(matched_game_id, mkt_key)][book_name] = selections

        # Write one snapshot per (game, market) with all books
        odds_written = 0
        for (game_id, market_key), books in aggregated.items():
            write_live_snapshot(
                league=league_code,
                game_id=game_id,
                market_key=market_key,
                books=dict(books),
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
    from ..odds.client import PROP_MARKETS, OddsAPIClient
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

        # Get event IDs for our live games — extract data inside session
        # to avoid DetachedInstanceError when accessing attributes later.
        game_events: list[tuple[int, str]] = []  # (game_id, event_id)
        with get_session() as session:
            games = (
                session.query(db_models.SportsGame)
                .filter(
                    db_models.SportsGame.id.in_(game_ids),
                    db_models.SportsGame.status == "live",
                )
                .all()
            )
            for g in games:
                eid = (g.external_ids or {}).get("odds_api_event_id")
                if eid:
                    game_events.append((g.id, eid))

        events_processed = 0
        props_written = 0
        prop_markets = PROP_MARKETS.get(league_code.upper(), [])

        for game_id, event_id in game_events:

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
                game_id=game_id,
                qps_budget=0.5,
                qps_burst=2,
                params=params,
            )

            if response is None or response.status_code != 200:
                continue

            client._track_credits(response)
            payload = response.json()

            # Aggregate all bookmakers per market_key for this game
            aggregated: dict[str, dict[str, list[dict]]] = defaultdict(
                lambda: defaultdict(list)
            )

            for bookmaker in payload.get("bookmakers", []):
                book_name = bookmaker.get("title", "unknown")
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
                        aggregated[mkt_key][book_name] = selections

            for mkt_key, books in aggregated.items():
                write_live_snapshot(
                    league=league_code,
                    game_id=game_id,
                    market_key=mkt_key,
                    books=dict(books),
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
