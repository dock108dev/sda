"""Live NHL feed helpers (schedule, play-by-play, boxscores).

Uses the official NHL API (api-web.nhle.com) for all NHL data.

This module provides the main NHLLiveFeedClient which composes:
- NHLBoxscoreFetcher: Team and player boxscore data
- NHLPbpFetcher: Play-by-play data
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx

from ..config import settings
from ..logging import logger
from ..models import NormalizedPlayByPlay
from ..utils.cache import APICache
from ..utils.datetime_utils import start_of_et_day_utc
from ..utils.parsing import parse_int
from ..utils.provider_request import provider_request
from .nhl_boxscore import NHLBoxscoreFetcher
from .nhl_constants import NHL_SCHEDULE_URL
from .nhl_helpers import (
    build_team_identity_from_api,
    map_nhl_game_state,
    one_day,
)
from .nhl_models import NHLBoxscore, NHLLiveGame
from .nhl_pbp import NHLPbpFetcher

__all__ = [
    "NHLLiveGame",
    "NHLBoxscore",
    "NHLLiveFeedClient",
]


def _et_noon_utc(day: date):
    """Return UTC datetime for noon ET on the given date.

    Used for schedule matching — to_et_date() on this value always
    returns the correct calendar date regardless of DST.
    """
    return start_of_et_day_utc(day) + timedelta(hours=12)


class NHLLiveFeedClient:
    """Client for NHL live schedule + play-by-play endpoints using api-web.nhle.com.

    Composes separate fetchers for boxscore and PBP data.
    """

    def __init__(self) -> None:
        """Initialize the NHL live feed client."""
        timeout = settings.scraper_config.request_timeout_seconds
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "sports-data-admin-live/1.0"},
        )
        cache_dir = settings.scraper_config.html_cache_dir
        self._cache = APICache(cache_dir=cache_dir, api_name="nhl")

        # Compose fetchers
        self._boxscore_fetcher = NHLBoxscoreFetcher(self.client, self._cache)
        self._pbp_fetcher = NHLPbpFetcher(self.client, self._cache)

    def fetch_schedule(self, start: date, end: date) -> list[NHLLiveGame]:
        """Fetch NHL schedule for a date range.

        The NHL API provides schedule by single date, so we fetch each date
        in the range and combine results.

        Args:
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            List of NHLLiveGame objects for all games in the date range
        """
        games: list[NHLLiveGame] = []
        current = start

        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            url = NHL_SCHEDULE_URL.format(date=date_str)
            logger.info("nhl_schedule_fetch", url=url, date=date_str)

            try:
                response = provider_request(
                    self.client,
                    "GET",
                    url,
                    provider="nhl-api",
                    endpoint="schedule",
                    league="NHL",
                    qps_budget=5.0,
                    qps_burst=10,
                )
            except Exception as exc:
                logger.error("nhl_schedule_fetch_error", date=date_str, error=str(exc))
                current += one_day()
                continue

            if response is None:
                current += one_day()
                continue

            if response.status_code != 200:
                logger.warning(
                    "nhl_schedule_fetch_failed",
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

    def _parse_schedule_response(self, payload: dict, target_date: date) -> list[NHLLiveGame]:
        """Parse the schedule response from the NHL API.

        The NHL API's gameWeek buckets each game under a single local
        ``date`` field, but a late-evening start crosses midnight UTC into
        the next calendar day (e.g. a 9pm ET puck drop on 2026-05-03 has
        startTimeUTC=2026-05-04T01:00:00Z and is filed under date=2026-05-03).
        Polling /schedule/2026-05-04 then returns nothing for that game,
        so it never gets a final-score update and stays stuck on 0-0.

        Include a game when either its NHL-bucketed date matches
        ``target_date`` or its ``startTimeUTC`` UTC-date does. Dedupe by
        game_id since both conditions can match for the same game.
        """
        games: list[NHLLiveGame] = []
        seen_ids: set[int] = set()

        game_week = payload.get("gameWeek", [])
        target_date_str = target_date.strftime("%Y-%m-%d")

        for day_data in game_week:
            day_date = day_data.get("date", "")
            for game in day_data.get("games", []):
                game_id = game.get("id")
                if not game_id or game_id in seen_ids:
                    continue

                start_time_str = game.get("startTimeUTC")
                start_dt: datetime | None = None
                if start_time_str:
                    try:
                        start_dt = datetime.fromisoformat(
                            start_time_str.replace("Z", "+00:00")
                        ).astimezone(UTC)
                    except (ValueError, TypeError):
                        start_dt = None

                matches_local_date = day_date == target_date_str
                matches_utc_start = (
                    start_dt is not None and start_dt.date() == target_date
                )
                if not (matches_local_date or matches_utc_start):
                    continue

                game_state = game.get("gameState", "")
                status_text = game.get("gameScheduleState")
                status = map_nhl_game_state(game_state, status_text)

                game_date = start_dt if start_dt is not None else _et_noon_utc(target_date)

                home_team_data = game.get("homeTeam", {})
                away_team_data = game.get("awayTeam", {})

                home_team = build_team_identity_from_api(home_team_data)
                away_team = build_team_identity_from_api(away_team_data)

                home_score = parse_int(home_team_data.get("score"))
                away_score = parse_int(away_team_data.get("score"))

                games.append(
                    NHLLiveGame(
                        game_id=game_id,
                        game_date=game_date,
                        status=status,
                        status_text=status_text,
                        home_team=home_team,
                        away_team=away_team,
                        home_score=home_score,
                        away_score=away_score,
                    )
                )
                seen_ids.add(game_id)

        return games

    # Delegate PBP methods to PBP fetcher
    def fetch_play_by_play(self, game_id: int) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game."""
        return self._pbp_fetcher.fetch_play_by_play(game_id)

    # Delegate boxscore methods to boxscore fetcher
    def fetch_boxscore(self, game_id: int) -> NHLBoxscore | None:
        """Fetch boxscore from NHL API."""
        return self._boxscore_fetcher.fetch_boxscore(game_id)
