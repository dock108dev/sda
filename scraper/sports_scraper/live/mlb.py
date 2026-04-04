"""Live MLB feed helpers (schedule, play-by-play, boxscores).

Uses the official MLB Stats API (statsapi.mlb.com) for all MLB data.

This module provides the main MLBLiveFeedClient which composes:
- MLBBoxscoreFetcher: Team and player boxscore data
- MLBPbpFetcher: Play-by-play data
"""

from __future__ import annotations

from datetime import date

import httpx

from ..config import settings
from ..logging import logger
from ..models import NormalizedPlayByPlay
from ..utils.cache import APICache
from ..utils.datetime_utils import start_of_et_day_utc
from ..utils.parsing import parse_int
from .mlb_boxscore import MLBBoxscoreFetcher
from .mlb_constants import MLB_SCHEDULE_URL
from .mlb_helpers import (
    build_team_identity_from_api,
    map_mlb_game_state,
    one_day,
    parse_datetime,
)
from .mlb_models import MLBBoxscore, MLBLiveGame
from .mlb_pbp import MLBPbpFetcher
from .mlb_statcast import (
    MLBStatcastFetcher,
    PitcherStatcastAggregates,
    PlayerStatcastAggregates,
    TeamStatcastAggregates,
)

__all__ = [
    "MLBLiveGame",
    "MLBBoxscore",
    "MLBLiveFeedClient",
    "PitcherStatcastAggregates",
    "PlayerStatcastAggregates",
    "TeamStatcastAggregates",
]


class MLBLiveFeedClient:
    """Client for MLB live schedule + play-by-play endpoints using statsapi.mlb.com.

    Composes separate fetchers for boxscore and PBP data.
    """

    def __init__(self) -> None:
        """Initialize the MLB live feed client."""
        timeout = settings.scraper_config.request_timeout_seconds
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "sports-data-admin-live/1.0"},
        )
        cache_dir = settings.scraper_config.html_cache_dir
        self._cache = APICache(cache_dir=cache_dir, api_name="mlb")

        # Compose fetchers
        self._boxscore_fetcher = MLBBoxscoreFetcher(self.client, self._cache)
        self._pbp_fetcher = MLBPbpFetcher(self.client, self._cache)
        self._statcast_fetcher = MLBStatcastFetcher(self.client, self._cache)

    def fetch_schedule(self, start: date, end: date) -> list[MLBLiveGame]:
        """Fetch MLB schedule for a date range.

        The MLB API supports fetching by single date, so we iterate each date.
        """
        games: list[MLBLiveGame] = []
        current = start

        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            url = MLB_SCHEDULE_URL.format(date=date_str)
            logger.info("mlb_schedule_fetch", url=url, date=date_str)

            try:
                response = self.client.get(url)
            except Exception as exc:
                logger.error("mlb_schedule_fetch_error", date=date_str, error=str(exc))
                current += one_day()
                continue

            if response.status_code != 200:
                logger.warning(
                    "mlb_schedule_fetch_failed",
                    date=date_str,
                    status=response.status_code,
                )
                current += one_day()
                continue

            payload = response.json()
            day_games = self._parse_schedule_response(payload, current)
            games.extend(day_games)

            current += one_day()

        return games

    def _parse_schedule_response(self, payload: dict, target_date: date) -> list[MLBLiveGame]:
        """Parse the schedule response from the MLB Stats API.

        The API structure has dates[] array with games[] inside each date.
        """
        games: list[MLBLiveGame] = []

        for date_entry in payload.get("dates", []):
            for game_data in date_entry.get("games", []):
                game_pk = game_data.get("gamePk")
                if not game_pk:
                    continue

                # Get status
                status_data = game_data.get("status", {})
                abstract_state = status_data.get("abstractGameState", "")
                status_code = status_data.get("statusCode", "")
                status = map_mlb_game_state(abstract_state or status_code)

                game_date_str = game_data.get("gameDate")
                if not game_date_str:
                    logger.warning("mlb_missing_game_date", game_pk=game_data.get("gamePk"))
                    continue
                game_date = parse_datetime(game_date_str)

                # Extract team info
                teams = game_data.get("teams", {})
                home_team_data = teams.get("home", {})
                away_team_data = teams.get("away", {})

                home_team = build_team_identity_from_api(home_team_data)
                away_team = build_team_identity_from_api(away_team_data)

                # Extract scores
                home_score = parse_int(home_team_data.get("score"))
                away_score = parse_int(away_team_data.get("score"))

                # Extract venue and weather
                venue_data = game_data.get("venue", {})
                venue_name = venue_data.get("name")

                weather = game_data.get("weather")

                # Extract game type code (R=regular, P/F/D/L/W=postseason, etc.)
                game_type = game_data.get("gameType")

                games.append(
                    MLBLiveGame(
                        game_pk=game_pk,
                        game_date=game_date,
                        status=status,
                        home_team=home_team,
                        away_team=away_team,
                        home_score=home_score,
                        away_score=away_score,
                        venue=venue_name,
                        weather=weather,
                        game_type=game_type,
                    )
                )

        return games

    # Delegate PBP methods to PBP fetcher
    def fetch_play_by_play(
        self, game_pk: int, game_status: str | None = None
    ) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game."""
        return self._pbp_fetcher.fetch_play_by_play(game_pk, game_status=game_status)

    # Delegate statcast methods to statcast fetcher
    def fetch_statcast_aggregates(
        self, game_pk: int, game_status: str | None = None
    ) -> dict[str, TeamStatcastAggregates]:
        """Fetch and aggregate Statcast data for a game."""
        return self._statcast_fetcher.fetch_statcast_aggregates(game_pk, game_status=game_status)

    def fetch_player_statcast_aggregates(
        self, game_pk: int, game_status: str | None = None
    ) -> list[PlayerStatcastAggregates]:
        """Fetch and aggregate per-batter Statcast data for a game."""
        return self._statcast_fetcher.fetch_player_statcast_aggregates(
            game_pk, game_status=game_status
        )

    def fetch_pitcher_statcast_aggregates(
        self, game_pk: int, game_status: str | None = None
    ) -> list[PitcherStatcastAggregates]:
        """Fetch and aggregate per-pitcher Statcast data for a game."""
        return self._statcast_fetcher.fetch_pitcher_statcast_aggregates(
            game_pk, game_status=game_status
        )

    # Delegate boxscore methods to boxscore fetcher
    def fetch_boxscore(self, game_pk: int, game_status: str | None = None) -> MLBBoxscore | None:
        """Fetch boxscore from MLB Stats API."""
        return self._boxscore_fetcher.fetch_boxscore(game_pk, game_status=game_status)

    def fetch_boxscore_raw(self, game_pk: int, game_status: str | None = None) -> dict | None:
        """Fetch raw boxscore JSON dict from MLB Stats API."""
        return self._boxscore_fetcher.fetch_boxscore_raw(game_pk, game_status=game_status)
