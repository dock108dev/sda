"""Live NBA feed helpers (scoreboard + play-by-play + boxscores).

Uses the NBA CDN API (cdn.nba.com) for all NBA data.

This module provides the main NBALiveFeedClient which composes:
- NBABoxscoreFetcher: Team and player boxscore data
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from ..config import settings
from ..logging import logger
from ..models import NormalizedPlay, NormalizedPlayByPlay
from ..utils.cache import APICache
from ..utils.datetime_utils import now_utc
from ..utils.parsing import parse_int
from .nba_boxscore import NBABoxscoreFetcher
from .nba_models import NBABoxscore

# NBA retired date-specific scoreboard URLs (403). The generic _00 endpoint
# always returns the current NBA-day scoreboard with live status + scores.
NBA_SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
NBA_PBP_URL = "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
NBA_PERIOD_MULTIPLIER = 10000

_CLOCK_PATTERN = re.compile(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")


@dataclass(frozen=True)
class NBALiveGame:
    game_id: str
    game_date: datetime
    status: str
    status_text: str | None
    home_abbr: str
    away_abbr: str
    home_score: int | None
    away_score: int | None


class NBALiveFeedClient:
    """Client for NBA live scoreboard + play-by-play + boxscore endpoints.

    Composes NBABoxscoreFetcher for boxscore data.
    """

    def __init__(self) -> None:
        timeout = settings.scraper_config.request_timeout_seconds
        # NBA CDN requires browser-like headers to avoid 403 errors
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com",
        }
        self.client = httpx.Client(timeout=timeout, headers=headers)
        cache_dir = settings.scraper_config.html_cache_dir
        self._cache = APICache(cache_dir=cache_dir, api_name="nba")
        self._boxscore_fetcher = NBABoxscoreFetcher(self.client, self._cache)

    def fetch_scoreboard(self, day: date) -> list[NBALiveGame]:
        """Fetch games for a specific date.

        Tries the live scoreboard first (has real status + scores),
        falls back to the static schedule API (game IDs only, no live status).

        The live scoreboard endpoint always returns today's games regardless of
        the requested date, so we skip it for past dates and go straight to the
        schedule API which has the full season's game IDs.
        """
        from ..utils.datetime_utils import today_et

        # Live scoreboard only has today's games; use schedule API for past dates
        if day >= today_et():
            live_games = self._fetch_live_scoreboard(day)
            if live_games:
                return live_games

        # Schedule API for past dates (live scoreboard only has today's games)
        logger.info(
            "nba_scoreboard_using_schedule",
            date=str(day),
        )
        return self._fetch_games_from_schedule(day)

    def _fetch_live_scoreboard(self, day: date) -> list[NBALiveGame]:
        """Fetch the live scoreboard with real status + scores.

        Uses the generic _00 endpoint which returns the current NBA-day games.
        The `day` parameter is logged but no longer used to build the URL.
        """
        url = NBA_SCOREBOARD_URL
        logger.info("nba_scoreboard_fetch", url=url, date=str(day))
        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.warning("nba_scoreboard_fetch_error", date=str(day), error=str(exc))
            return []

        if response.status_code == 403:
            logger.debug("nba_scoreboard_blocked", status=403, date=str(day))
            return []

        if response.status_code != 200:
            logger.warning("nba_scoreboard_fetch_failed", status=response.status_code, date=str(day))
            return []

        payload = response.json()
        scoreboard_games = payload.get("scoreboard", {}).get("games", [])
        live_games: list[NBALiveGame] = []
        for game in scoreboard_games:
            game_id = str(game.get("gameId"))
            game_status = game.get("gameStatus")
            status_text = game.get("gameStatusText")
            if game_status == 2:
                status = "live"
            elif game_status == 3:
                status = "final"
            else:
                status = "scheduled"

            game_date = _parse_nba_game_datetime(game.get("gameEt"))
            home_team = game.get("homeTeam", {})
            away_team = game.get("awayTeam", {})
            live_games.append(
                NBALiveGame(
                    game_id=game_id,
                    game_date=game_date,
                    status=status,
                    status_text=status_text,
                    home_abbr=str(home_team.get("teamTricode", "")),
                    away_abbr=str(away_team.get("teamTricode", "")),
                    home_score=parse_int(home_team.get("score")),
                    away_score=parse_int(away_team.get("score")),
                )
            )

        logger.info("nba_scoreboard_parsed", count=len(live_games), date=str(day))
        return live_games

    def _fetch_games_from_schedule(self, day: date) -> list[NBALiveGame]:
        """Fetch games for a date from the season schedule API.

        The schedule API contains all games for the season and is more reliable
        than the date-specific scoreboard endpoint which may be blocked.
        """
        logger.info("nba_schedule_fetch", url=NBA_SCHEDULE_URL, date=str(day))
        try:
            response = self.client.get(NBA_SCHEDULE_URL, timeout=30.0)
            if response.status_code != 200:
                logger.warning("nba_schedule_fetch_failed", status=response.status_code)
                return []

            payload = response.json()
            game_dates = payload.get("leagueSchedule", {}).get("gameDates", [])

            # Format date to match schedule format: "MM/DD/YYYY 00:00:00"
            target_date_str = day.strftime("%m/%d/%Y")

            live_games: list[NBALiveGame] = []
            for date_obj in game_dates:
                game_date_str = date_obj.get("gameDate", "")
                if not game_date_str.startswith(target_date_str):
                    continue

                for game in date_obj.get("games", []):
                    game_id = str(game.get("gameId", ""))
                    if not game_id:
                        continue

                    home_team = game.get("homeTeam", {})
                    away_team = game.get("awayTeam", {})
                    game_datetime = _parse_nba_game_datetime(game.get("gameDateTimeEst"))

                    # Schedule doesn't have live status, default to scheduled
                    live_games.append(
                        NBALiveGame(
                            game_id=game_id,
                            game_date=game_datetime,
                            status="scheduled",
                            status_text=None,
                            home_abbr=str(home_team.get("teamTricode", "")),
                            away_abbr=str(away_team.get("teamTricode", "")),
                            home_score=None,
                            away_score=None,
                        )
                    )
                break  # Found the target date, no need to continue

            logger.info("nba_schedule_parsed", count=len(live_games), date=str(day))
            return live_games

        except Exception as exc:
            logger.warning("nba_schedule_fetch_error", error=str(exc))
            return []

    def fetch_play_by_play(self, game_id: str) -> NormalizedPlayByPlay:
        url = NBA_PBP_URL.format(game_id=game_id)
        logger.info("nba_pbp_fetch", url=url, game_id=game_id)
        response = self.client.get(url)
        if response.status_code == 403:
            logger.debug("nba_pbp_blocked", game_id=game_id, status=403)
            return NormalizedPlayByPlay(source_game_key=game_id, plays=[])

        if response.status_code != 200:
            logger.warning("nba_pbp_fetch_failed", game_id=game_id, status=response.status_code)
            return NormalizedPlayByPlay(source_game_key=game_id, plays=[])

        payload = response.json()
        actions = payload.get("game", {}).get("actions", [])
        plays: list[NormalizedPlay] = []
        for action in actions:
            period = parse_int(action.get("period"))
            sequence = parse_int(action.get("actionNumber"))
            if sequence is None:
                continue

            play_index = (period or 0) * NBA_PERIOD_MULTIPLIER + sequence
            clock_value = _parse_nba_clock(action.get("clock"))

            plays.append(
                NormalizedPlay(
                    play_index=play_index,
                    quarter=period,
                    game_clock=clock_value,
                    play_type=str(action.get("actionType")) if action.get("actionType") else None,
                    team_abbreviation=action.get("teamTricode"),
                    player_id=str(action.get("personId")) if action.get("personId") else None,
                    player_name=action.get("playerName"),
                    description=action.get("description"),
                    home_score=parse_int(action.get("scoreHome")),
                    away_score=parse_int(action.get("scoreAway")),
                    raw_data={
                        "event_time": action.get("timeActual") or action.get("timeActualUTC"),
                        "clock": action.get("clock"),
                        "period": period,
                        "sequence": sequence,
                    },
                )
            )

        logger.info("nba_pbp_parsed", game_id=game_id, count=len(plays))
        return NormalizedPlayByPlay(source_game_key=game_id, plays=plays)

    # Delegate boxscore methods to boxscore fetcher
    def fetch_boxscore(self, game_id: str) -> NBABoxscore | None:
        """Fetch boxscore from NBA CDN API."""
        return self._boxscore_fetcher.fetch_boxscore(game_id)


def _parse_nba_game_datetime(value: str | None) -> datetime:
    if not value:
        return now_utc()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC)
    except ValueError:
        return now_utc()


def _parse_nba_clock(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("PT"):
        match = _CLOCK_PATTERN.match(value)
        if match:
            minutes = int(match.group(1) or 0)
            seconds = float(match.group(2) or 0)
            return f"{minutes}:{int(seconds):02d}"
    return value


