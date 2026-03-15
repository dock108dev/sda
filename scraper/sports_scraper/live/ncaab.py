"""NCAAB live feed helpers (schedule, play-by-play, boxscores).

Uses two complementary data sources:
- CBB API (api.collegebasketballdata.com): schedule lookup, batch boxscores
- NCAA API (ncaa-api.henrygd.me): live scoreboard, PBP, per-game boxscores

This module provides the main NCAABLiveFeedClient which composes:
- CBB API: NCAABBoxscoreFetcher, NCAABPbpFetcher
- NCAA API: NCAAScoreboardClient, NCAAPbpFetcher, NCAABoxscoreFetcher
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from ..config import settings
from ..logging import logger
from ..models import NormalizedPlayByPlay
from ..utils.cache import APICache
from ..utils.date_utils import season_ending_year
from ..utils.datetime_utils import eastern_date_range_to_utc_iso
from ..utils.parsing import parse_int
from .ncaa_boxscore import NCAABoxscoreFetcher
from .ncaa_pbp import NCAAPbpFetcher
from .ncaa_scoreboard import NCAAScoreboardClient, NCAAScoreboardGame
from .ncaab_boxscore import NCAABBoxscoreFetcher
from .ncaab_constants import CBB_GAMES_URL
from .ncaab_models import NCAABBoxscore, NCAABLiveGame
from .ncaab_pbp import NCAABPbpFetcher

__all__ = [
    "NCAABLiveGame",
    "NCAABBoxscore",
    "NCAABLiveFeedClient",
    "NCAAScoreboardGame",
]


class NCAABLiveFeedClient:
    """Client for NCAAB data using both CBB API and NCAA API.

    Composes separate fetchers for boxscore and PBP data:
    - CBB API (api.collegebasketballdata.com): schedule lookup, batch boxscores
    - NCAA API (ncaa-api.henrygd.me): live scoreboard, PBP, per-game boxscores
    """

    def __init__(self) -> None:
        """Initialize the NCAAB live feed client."""
        api_key = settings.cbb_stats_api_key
        if not api_key:
            logger.warning("ncaab_no_api_key", msg="CBB_STATS_API_KEY not set")

        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=30.0,
        )
        cache_dir = settings.scraper_config.html_cache_dir
        self._cache = APICache(cache_dir=cache_dir, api_name="ncaab")

        # Team names cache for display purposes
        self._team_names: dict[int, str] = {}
        self._team_names_loaded_for_season: int | None = None

        # CBB API fetchers (schedule, batch boxscores)
        self._boxscore_fetcher = NCAABBoxscoreFetcher(self.client, self._cache)
        self._pbp_fetcher = NCAABPbpFetcher(self.client, self._cache)

        # NCAA API fetchers (live scoreboard, PBP, per-game boxscores)
        self._ncaa_client = httpx.Client(timeout=15.0)
        ncaa_cache = APICache(cache_dir=cache_dir, api_name="ncaa")
        self._ncaa_scoreboard = NCAAScoreboardClient(self._ncaa_client)
        self._ncaa_pbp = NCAAPbpFetcher(self._ncaa_client, ncaa_cache)
        self._ncaa_boxscore = NCAABoxscoreFetcher(self._ncaa_client, ncaa_cache)

    def _get_season_for_date(self, game_date: date) -> int:
        """Get the season year for a given date.

        NCAAB season spans two calendar years. Season 2025 runs from
        roughly November 2024 through April 2025. We use the ending year.
        """
        return season_ending_year(game_date)

    def _ensure_team_names(self, season: int) -> None:
        """Ensure team names are loaded for the given season."""
        if self._team_names_loaded_for_season == season:
            return

        logger.info("ncaab_loading_team_names", season=season)

        try:
            params = {"season": season}
            response = self.client.get(CBB_GAMES_URL, params=params)
            if response.status_code == 200:
                games = response.json()
                for game in games[:500]:  # Limit to avoid memory issues
                    # API returns team IDs and names at root level
                    home_id = game.get("homeTeamId")
                    away_id = game.get("awayTeamId")
                    home_name = game.get("homeTeam")
                    away_name = game.get("awayTeam")

                    if home_id and home_name:
                        self._team_names[home_id] = home_name
                    if away_id and away_name:
                        self._team_names[away_id] = away_name

                self._team_names_loaded_for_season = season
                logger.info("ncaab_team_names_loaded", count=len(self._team_names))
        except Exception as exc:
            logger.warning("ncaab_team_names_load_failed", error=str(exc))

    def _get_team_display_name(self, team_id: int, fallback: str) -> str:
        """Get display name for a team, with fallback."""
        return self._team_names.get(team_id, fallback)

    def fetch_games(
        self,
        start_date: date,
        end_date: date,
        season: int | None = None,
    ) -> list[NCAABLiveGame]:
        """Fetch games for a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            season: Season year (optional, will be inferred from start_date)

        Returns:
            List of NCAABLiveGame objects
        """
        if season is None:
            season = self._get_season_for_date(start_date)

        self._ensure_team_names(season)

        params: dict[str, Any] = {"season": season}

        # Add date range filters - API requires ISO 8601 format in UTC
        start_utc_iso, end_utc_iso = eastern_date_range_to_utc_iso(start_date, end_date)
        params["startDateRange"] = start_utc_iso
        params["endDateRange"] = end_utc_iso

        logger.info(
            "ncaab_games_fetch",
            start_date=str(start_date),
            end_date=str(end_date),
            season=season,
        )

        try:
            response = self.client.get(CBB_GAMES_URL, params=params)
        except Exception as exc:
            logger.error(
                "ncaab_games_fetch_error",
                start_date=str(start_date),
                end_date=str(end_date),
                error=str(exc),
            )
            return []

        if response.status_code != 200:
            logger.warning(
                "ncaab_games_fetch_failed",
                start_date=str(start_date),
                end_date=str(end_date),
                status=response.status_code,
            )
            return []

        games_data = response.json()
        logger.info(
            "ncaab_games_response",
            count=len(games_data) if isinstance(games_data, list) else 1,
        )

        games: list[NCAABLiveGame] = []
        for game in games_data:
            parsed = self._parse_game(game, season)
            if parsed:
                games.append(parsed)

        return games

    def _parse_game(self, game: dict, season: int) -> NCAABLiveGame | None:
        """Parse a game from the API response."""
        # API uses 'id' not 'gameId'
        game_id = game.get("id")
        if not game_id:
            return None

        # API uses 'startDate' not 'gameDate'
        date_str = game.get("startDate")
        if date_str:
            try:
                game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                game_date = datetime.now()
        else:
            game_date = datetime.now()

        # Team IDs are at root level, not nested
        home_team_id = game.get("homeTeamId") or 0
        away_team_id = game.get("awayTeamId") or 0

        # Team names are strings at root level
        home_team_name = game.get("homeTeam") or self._get_team_display_name(home_team_id, "Unknown")
        away_team_name = game.get("awayTeam") or self._get_team_display_name(away_team_id, "Unknown")

        # Map status
        status_raw = game.get("status") or ""
        if status_raw.lower() in ["final", "complete", "completed"]:
            status = "final"
        elif status_raw.lower() in ["live", "in progress", "inprogress", "in_progress"]:
            status = "live"
        elif status_raw.lower() in ["postponed"]:
            status = "postponed"
        elif status_raw.lower() in ["canceled", "cancelled"]:
            status = "canceled"
        else:
            status = "scheduled"

        # API uses 'homePoints'/'awayPoints' not 'homeScore'/'awayScore'
        home_score = parse_int(game.get("homePoints"))
        away_score = parse_int(game.get("awayPoints"))

        return NCAABLiveGame(
            game_id=game_id,
            game_date=game_date,
            status=status,
            season=season,
            home_team_id=home_team_id,
            home_team_name=home_team_name,
            away_team_id=away_team_id,
            away_team_name=away_team_name,
            home_score=home_score,
            away_score=away_score,
            neutral_site=game.get("neutralSite", False),
        )

    # Delegate boxscore methods to boxscore fetcher
    def fetch_game_teams_by_date_range(
        self, start_date: date, end_date: date, season: int
    ) -> list[dict]:
        """Fetch team-level boxscore stats for a date range."""
        return self._boxscore_fetcher.fetch_game_teams_by_date_range(start_date, end_date, season)

    def fetch_game_players_by_date_range(
        self, start_date: date, end_date: date, season: int
    ) -> list[dict]:
        """Fetch player-level boxscore stats for a date range."""
        return self._boxscore_fetcher.fetch_game_players_by_date_range(start_date, end_date, season)

    def fetch_boxscores_batch(
        self,
        game_ids: list[int],
        start_date: date,
        end_date: date,
        season: int,
        team_names_by_game: dict[int, tuple[str, str]],
    ) -> dict[int, NCAABBoxscore]:
        """Fetch boxscores for multiple games in batch API calls."""
        return self._boxscore_fetcher.fetch_boxscores_batch(
            game_ids, start_date, end_date, season, team_names_by_game
        )

    def fetch_boxscore(self, game: NCAABLiveGame) -> NCAABBoxscore | None:
        """Fetch full boxscore for a game."""
        return self._boxscore_fetcher.fetch_boxscore(game)

    def fetch_boxscore_by_id(
        self,
        game_id: int,
        season: int,
        game_date: datetime,
        home_team_name: str,
        away_team_name: str,
    ) -> NCAABBoxscore | None:
        """Fetch boxscore directly by game ID."""
        return self._boxscore_fetcher.fetch_boxscore_by_id(
            game_id, season, game_date, home_team_name, away_team_name
        )

    # Delegate PBP methods to PBP fetcher
    def fetch_play_by_play(
        self, game_id: int, game_status: str | None = None,
    ) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game."""
        return self._pbp_fetcher.fetch_play_by_play(game_id, game_status=game_status)

    # --- NCAA API delegation methods ---

    def fetch_ncaa_scoreboard(self, game_date=None) -> list[NCAAScoreboardGame]:
        """Fetch NCAA scoreboard for live game states.

        Args:
            game_date: Specific date to fetch. None = today's scoreboard.
        """
        return self._ncaa_scoreboard.fetch_scoreboard(game_date)

    def fetch_ncaa_play_by_play(
        self,
        ncaa_game_id: str,
        game_status: str | None = None,
        home_abbr: str | None = None,
        away_abbr: str | None = None,
    ) -> NormalizedPlayByPlay:
        """Fetch PBP from the NCAA API for a game."""
        return self._ncaa_pbp.fetch_play_by_play(
            ncaa_game_id,
            game_status=game_status,
            home_abbr=home_abbr,
            away_abbr=away_abbr,
        )

    def fetch_ncaa_boxscore(
        self,
        ncaa_game_id: str,
        home_team_name: str,
        away_team_name: str,
        game_status: str | None = None,
    ) -> NCAABBoxscore | None:
        """Fetch boxscore from the NCAA API for a game."""
        return self._ncaa_boxscore.fetch_boxscore(
            ncaa_game_id, home_team_name, away_team_name, game_status=game_status,
        )
