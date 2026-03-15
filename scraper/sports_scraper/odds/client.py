"""Odds API client for pulling mainline closing prices.

Supports both live odds (upcoming games) and historical odds (past games).
Uses The Odds API: https://the-odds-api.com/liveapi/guides/v4/

Includes local JSON caching to avoid repeat API calls and save credits.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..logging import logger
from ..models import NormalizedOddsSnapshot
from .parser import parse_odds_events, parse_prop_event

SPORT_KEY_MAP = {
    "NBA": "basketball_nba",
    "NCAAB": "basketball_ncaab",
    "NFL": "americanfootball_nfl",
    "NCAAF": "americanfootball_ncaaf",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
}

MARKET_TYPES = {
    "spreads": "spread",
    "totals": "total",
    "h2h": "moneyline",
}

# NHL uses "spreads" for puck lines; keep the canonical "spread" market type.

# Prop market keys by sport
PROP_MARKETS: dict[str, list[str]] = {
    "NBA": [
        "player_points", "player_rebounds", "player_assists", "player_threes",
        "player_points_rebounds_assists", "player_blocks", "player_steals",
        "team_totals", "alternate_spreads", "alternate_totals",
    ],
    "NCAAB": [
        "player_points", "player_rebounds", "player_assists", "player_threes",
        "player_points_rebounds_assists", "player_blocks", "player_steals",
        "team_totals", "alternate_spreads", "alternate_totals",
    ],
    "NHL": [
        "player_points", "player_goals", "player_assists",
        "player_shots_on_goal", "player_total_saves",
        "team_totals", "alternate_spreads", "alternate_totals",
    ],
    "MLB": [
        "batter_hits", "batter_total_bases", "batter_rbis",
        "batter_runs_scored", "batter_home_runs", "batter_stolen_bases",
        "pitcher_strikeouts", "pitcher_outs", "pitcher_hits_allowed",
        "pitcher_walks", "pitcher_earned_runs",
        "team_totals", "alternate_spreads", "alternate_totals",
    ],
}

# Credit safety thresholds
CREDIT_WARNING_THRESHOLD = 1000
CREDIT_ABORT_THRESHOLD = 500

# Default snapshot times for closing lines (in UTC)
# Evening games typically close around these times
CLOSING_LINE_HOURS = {
    "NBA": 23,      # ~7 PM ET = 23:00 UTC (winter) / 11 PM UTC
    "NCAAB": 23,
    "NFL": 17,      # ~1 PM ET = 17:00 UTC (Sunday games)
    "NCAAF": 17,
    "MLB": 23,      # ~7 PM ET
    "NHL": 23,
}


class OddsAPIClient:
    def __init__(self) -> None:
        if not settings.odds_api_key:
            logger.warning("odds_api_key_missing", message="ODDS_API_KEY not configured; odds sync disabled.")
        self.client = httpx.Client(
            base_url=settings.odds_config.base_url,
            headers={"User-Agent": "dock108-odds-sync/1.0"},
            timeout=settings.odds_config.request_timeout_seconds,
        )
        # Cache directory for odds responses
        self._cache_dir = Path(settings.scraper_config.html_cache_dir) / "odds"
        # Track remaining credits from API response headers
        self._credits_remaining: int | None = None

    # Thin wrappers so tests that call client._parse_* still work
    def _parse_odds_events(self, league_code: str, events: list, books: list[str] | None = None) -> list:
        return parse_odds_events(league_code, events, books)

    def _parse_prop_event(self, league_code: str, event_data: dict) -> list:
        return parse_prop_event(league_code, event_data)

    def _truncate_body(self, body: str | None, limit: int = 500) -> str | None:
        if not body:
            return None
        if len(body) <= limit:
            return body
        return f"{body[:limit]}..."

    # -------------------------------------------------------------------------
    # Cache helpers
    # -------------------------------------------------------------------------
    def _get_cache_path(self, league: str, game_date: date, is_historical: bool) -> Path:
        """Get cache file path for an odds response."""
        prefix = "historical" if is_historical else "live"
        return self._cache_dir / league / f"{game_date}_{prefix}.json"

    def _read_cache(self, cache_path: Path, max_age_seconds: int | None = None) -> dict | None:
        """Read cached JSON response if it exists and is fresh enough.

        Args:
            cache_path: Path to the cache file
            max_age_seconds: If set, cache is only valid if younger than this many seconds
        """
        if cache_path.exists():
            try:
                # Check TTL if specified
                if max_age_seconds is not None:
                    file_age = datetime.now().timestamp() - cache_path.stat().st_mtime
                    if file_age > max_age_seconds:
                        logger.info(
                            "odds_cache_expired",
                            path=str(cache_path),
                            age_seconds=int(file_age),
                            max_age_seconds=max_age_seconds,
                        )
                        return None

                data = json.loads(cache_path.read_text())
                logger.debug("odds_cache_hit", path=str(cache_path))
                return data
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("odds_cache_read_error", path=str(cache_path), error=str(e))
        return None

    def _write_cache(self, cache_path: Path, data: Any) -> None:
        """Write API response to cache."""
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, indent=2, default=str))
            logger.debug("odds_cache_written", path=str(cache_path))
        except OSError as e:
            logger.warning("odds_cache_write_error", path=str(cache_path), error=str(e))

    # -------------------------------------------------------------------------
    # API methods
    # -------------------------------------------------------------------------
    def _sport_key(self, league_code: str) -> str | None:
        return SPORT_KEY_MAP.get(league_code.upper())

    def fetch_mainlines(
        self,
        league_code: str,
        start_date: date,
        end_date: date,
        books: list[str] | None = None,
    ) -> list[NormalizedOddsSnapshot]:
        """Fetch live odds for upcoming games.

        Uses the standard /sports/{sport}/odds endpoint.
        """
        if not settings.odds_api_key:
            return []

        sport_key = self._sport_key(league_code)
        if not sport_key:
            logger.warning("unsupported_league_for_odds", league=league_code)
            return []

        start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=UTC)
        end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=UTC)

        regions = ",".join(settings.odds_config.regions)
        params = {
            "apiKey": settings.odds_api_key,
            "regions": regions,
            "markets": ",".join(MARKET_TYPES.keys()),
            "oddsFormat": "american",
            "commenceTimeFrom": start_datetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commenceTimeTo": end_datetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if books:
            params["bookmakers"] = ",".join(books)

        response = self.client.get(f"/sports/{sport_key}/odds", params=params)
        if response.status_code != 200:
            logger.error(
                "odds_api_error",
                status=response.status_code,
                body=self._truncate_body(response.text),
            )
            return []

        payload = response.json()
        logger.info(
            "odds_api_response",
            league=league_code,
            event_count=len(payload) if isinstance(payload, list) else 0,
            remaining=response.headers.get("x-requests-remaining"),
        )

        return parse_odds_events(league_code, payload, books)

    def fetch_historical_odds(
        self,
        league_code: str,
        game_date: date,
        books: list[str] | None = None,
    ) -> list[NormalizedOddsSnapshot]:
        """Fetch historical odds for a specific date using the historical API.

        Uses /historical/sports/{sport}/odds endpoint.
        Cost: 30 credits per call (3 markets x 1 region).

        Args:
            league_code: League code (NBA, NFL, etc.)
            game_date: The date to fetch odds for
            books: Optional list of bookmaker keys to filter

        Returns:
            List of normalized odds snapshots for all games on that date
        """
        if not settings.odds_api_key:
            logger.warning("odds_api_key_missing", message="ODDS_API_KEY not configured")
            return []

        sport_key = self._sport_key(league_code)
        if not sport_key:
            logger.warning("unsupported_league_for_odds", league=league_code)
            return []

        # Check cache first
        cache_path = self._get_cache_path(league_code, game_date, is_historical=True)
        cached = self._read_cache(cache_path)
        if cached is not None:
            logger.info("odds_using_cache", league=league_code, date=str(game_date), type="historical")
            # Cached data is the full API response, extract events
            events = cached.get("data", []) if isinstance(cached, dict) else cached
            return parse_odds_events(league_code, events, books)

        # Build snapshot time - use closing line hour for this sport
        closing_hour = CLOSING_LINE_HOURS.get(league_code.upper(), 23)
        snapshot_dt = datetime.combine(game_date, time(closing_hour, 0), tzinfo=UTC)
        date_param = snapshot_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        regions = ",".join(settings.odds_config.regions)
        params = {
            "apiKey": settings.odds_api_key,
            "regions": regions,
            "markets": ",".join(MARKET_TYPES.keys()),
            "oddsFormat": "american",
            "date": date_param,
        }
        if books:
            params["bookmakers"] = ",".join(books)

        logger.info(
            "fetching_historical_odds",
            league=league_code,
            date=str(game_date),
            snapshot=date_param,
        )

        # FIX: Use /historical/sports/... not /v4/historical/sports/...
        # (base_url already includes /v4)
        response = self.client.get(f"/historical/sports/{sport_key}/odds", params=params)
        if response.status_code != 200:
            logger.error(
                "historical_odds_api_error",
                status=response.status_code,
                body=self._truncate_body(response.text),
            )
            return []

        result = response.json()

        # Log quota usage from headers
        remaining = response.headers.get("x-requests-remaining", "?")
        used = response.headers.get("x-requests-used", "?")
        cost = response.headers.get("x-requests-last", "?")
        logger.info(
            "historical_odds_quota",
            remaining=remaining,
            used=used,
            cost=cost,
        )

        # Cache the full response
        self._write_cache(cache_path, result)

        # Historical endpoint wraps data in a "data" field
        events = result.get("data", [])
        if not events:
            logger.info("no_historical_odds", league=league_code, date=str(game_date))
            return []

        logger.info(
            "historical_odds_response",
            league=league_code,
            date=str(game_date),
            event_count=len(events),
            snapshot_timestamp=result.get("timestamp"),
        )

        return parse_odds_events(league_code, events, books)

    def _track_credits(self, response: httpx.Response) -> int | None:
        """Parse and track credit usage from API response headers.

        Returns remaining credits or None if header not present.
        """
        remaining_str = response.headers.get("x-requests-remaining")
        if remaining_str is not None:
            try:
                remaining = int(remaining_str)
                self._credits_remaining = remaining

                if remaining < CREDIT_WARNING_THRESHOLD:
                    logger.warning(
                        "odds_credits_low",
                        remaining=remaining,
                        used=response.headers.get("x-requests-used"),
                        last_cost=response.headers.get("x-requests-last"),
                    )
                return remaining
            except ValueError:
                pass
        return None

    @property
    def should_abort_props(self) -> bool:
        """Check if prop sync should abort to preserve credits for mainlines."""
        return (
            self._credits_remaining is not None
            and self._credits_remaining < CREDIT_ABORT_THRESHOLD
        )

    def fetch_event_props(
        self,
        league_code: str,
        event_id: str,
        markets: list[str] | None = None,
    ) -> list[NormalizedOddsSnapshot]:
        """Fetch prop odds for a single event.

        Uses the /v4/sports/{sport}/events/{eventId}/odds endpoint.

        Args:
            league_code: League code (NBA, NHL, etc.)
            event_id: Odds API event ID
            markets: Optional list of prop market keys to fetch

        Returns:
            List of normalized odds snapshots for all prop markets.
        """
        if not settings.odds_api_key:
            return []

        sport_key = self._sport_key(league_code)
        if not sport_key:
            return []

        if markets is None:
            markets = PROP_MARKETS.get(league_code.upper(), [])
        if not markets:
            return []

        regions = ",".join(settings.odds_config.regions)
        params = {
            "apiKey": settings.odds_api_key,
            "regions": regions,
            "markets": ",".join(markets),
            "oddsFormat": "american",
        }

        response = self.client.get(
            f"/sports/{sport_key}/events/{event_id}/odds",
            params=params,
        )

        # Track credits
        self._track_credits(response)

        if response.status_code != 200:
            logger.error(
                "props_api_error",
                status=response.status_code,
                event_id=event_id,
                body=self._truncate_body(response.text),
            )
            return []

        payload = response.json()
        logger.info(
            "props_api_response",
            league=league_code,
            event_id=event_id,
            bookmaker_count=len(payload.get("bookmakers", [])),
            remaining=response.headers.get("x-requests-remaining"),
        )

        return parse_prop_event(league_code, payload)
