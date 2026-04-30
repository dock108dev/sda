"""Live NFL feed helpers (schedule, play-by-play, boxscores).

Uses the ESPN API (site.api.espn.com) for all NFL data. Free, no key required.

This module provides the main NFLLiveFeedClient which composes:
- NFLBoxscoreFetcher: Team and player boxscore data
- NFLPbpFetcher: Play-by-play data
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx

from ..config import settings
from ..logging import logger
from ..models import NormalizedPlayByPlay
from ..utils.cache import APICache
from ..utils.datetime_utils import start_of_et_day_utc
from ..utils.parsing import parse_int
from ..utils.provider_request import provider_request
from .nfl_boxscore import NFLBoxscoreFetcher
from .nfl_constants import NFL_SCOREBOARD_URL, NFL_SEASON_TYPE_MAP
from .nfl_helpers import build_team_identity_from_espn, map_espn_game_status, parse_espn_datetime
from .nfl_models import NFLBoxscore, NFLLiveGame
from .nfl_pbp import NFLPbpFetcher

__all__ = [
    "NFLLiveGame",
    "NFLBoxscore",
    "NFLLiveFeedClient",
]


def _et_noon_utc(day: date):
    """Return UTC datetime for noon ET on the given date."""
    return start_of_et_day_utc(day) + timedelta(hours=12)


class NFLLiveFeedClient:
    """Client for NFL live schedule + play-by-play via ESPN API.

    Composes separate fetchers for boxscore and PBP data.
    """

    def __init__(self) -> None:
        timeout = settings.scraper_config.request_timeout_seconds
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "sports-data-admin-live/1.0"},
        )
        cache_dir = settings.scraper_config.html_cache_dir
        self._cache = APICache(cache_dir=cache_dir, api_name="nfl")

        # Compose fetchers
        self._boxscore_fetcher = NFLBoxscoreFetcher(self.client, self._cache)
        self._pbp_fetcher = NFLPbpFetcher(self.client, self._cache)

    def fetch_schedule(self, start: date, end: date) -> list[NFLLiveGame]:
        """Fetch NFL schedule for a date range via ESPN scoreboard.

        Args:
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            List of NFLLiveGame objects for all games in the date range
        """
        games: list[NFLLiveGame] = []
        current = start

        while current <= end:
            date_str = current.strftime("%Y%m%d")
            url = NFL_SCOREBOARD_URL.format(date=date_str)
            logger.info("nfl_schedule_fetch", url=url, date=date_str)

            try:
                response = provider_request(
                    self.client,
                    "GET",
                    url,
                    provider="espn-api",
                    endpoint="scoreboard",
                    league="NFL",
                    qps_budget=5.0,
                    qps_burst=10,
                )
            except Exception as exc:
                logger.error("nfl_schedule_fetch_error", date=date_str, error=str(exc))
                current += timedelta(days=1)
                continue

            if response is None:
                current += timedelta(days=1)
                continue

            if response.status_code != 200:
                logger.warning(
                    "nfl_schedule_fetch_failed",
                    date=date_str,
                    status=response.status_code,
                )
                current += timedelta(days=1)
                continue

            payload = response.json()
            day_games = self._parse_scoreboard_response(payload, current)
            games.extend(day_games)

            current += timedelta(days=1)

        return games

    def _parse_scoreboard_response(self, payload: dict, target_date: date) -> list[NFLLiveGame]:
        """Parse ESPN scoreboard response into NFLLiveGame objects."""
        games: list[NFLLiveGame] = []

        events = payload.get("events", [])
        for event in events:
            game_id = parse_int(event.get("id"))
            if not game_id:
                continue

            # Status
            status_data = event.get("status", {})
            status_type_name = status_data.get("type", {}).get("name", "")
            status = map_espn_game_status(status_type_name)
            status_text = status_data.get("type", {}).get("shortDetail")

            # Game date
            game_date_str = event.get("date")
            if not game_date_str:
                logger.warning("nfl_missing_game_date", event_id=event.get("id"))
                continue
            game_date = parse_espn_datetime(game_date_str)

            # Season type — skip preseason by default
            season_data = event.get("season", {})
            season_type_id = parse_int(season_data.get("type")) or 2
            season_type = NFL_SEASON_TYPE_MAP.get(season_type_id, "regular")

            # Extract teams from competitions
            competitions = event.get("competitions", [])
            if not competitions:
                continue

            competition = competitions[0]
            competitors = competition.get("competitors", [])

            home_team_data = None
            away_team_data = None
            home_score = None
            away_score = None

            for comp in competitors:
                team_info = comp.get("team", {})
                if comp.get("homeAway") == "home":
                    home_team_data = team_info
                    home_score = parse_int(comp.get("score"))
                else:
                    away_team_data = team_info
                    away_score = parse_int(comp.get("score"))

            if not home_team_data or not away_team_data:
                continue

            home_team = build_team_identity_from_espn(home_team_data)
            away_team = build_team_identity_from_espn(away_team_data)

            games.append(
                NFLLiveGame(
                    game_id=game_id,
                    game_date=game_date,
                    status=status,
                    status_text=status_text,
                    home_team=home_team,
                    away_team=away_team,
                    home_score=home_score,
                    away_score=away_score,
                    season_type=season_type,
                )
            )

        return games

    def fetch_play_by_play(self, game_id: int) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game."""
        return self._pbp_fetcher.fetch_play_by_play(game_id)

    def fetch_boxscore(self, game_id: int) -> NFLBoxscore | None:
        """Fetch boxscore from ESPN summary API."""
        return self._boxscore_fetcher.fetch_boxscore(game_id)
