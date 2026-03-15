"""NCAA scoreboard client for real-time NCAAB game states.

Fetches the NCAA API D1 men's basketball scoreboard to determine which games
are live, final, or scheduled. Used as the primary source for NCAAB status
transitions during polling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx

from ..logging import logger
from ..utils.parsing import parse_int
from .ncaa_constants import NCAA_GAME_STATE_MAP, NCAA_SCOREBOARD_URL


@dataclass(frozen=True)
class NCAAScoreboardGame:
    """A single game from the NCAA scoreboard response."""

    ncaa_game_id: str
    game_state: str  # Normalized: "live", "final", "scheduled"
    home_team_short: str  # e.g. "Purdue"
    away_team_short: str  # e.g. "Indiana"
    home_team_seo: str  # e.g. "purdue"
    away_team_seo: str  # e.g. "indiana"
    home_score: int | None
    away_score: int | None
    current_period: int | None
    contest_clock: str | None  # e.g. "12:34"
    start_time_epoch: int | None


class NCAAScoreboardClient:
    """Client for the NCAA scoreboard API endpoint."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def fetch_scoreboard(self, game_date: date | None = None) -> list[NCAAScoreboardGame]:
        """Fetch D1 men's basketball scoreboard.

        Args:
            game_date: Specific date to fetch. None = today's scoreboard.

        Returns:
            List of NCAAScoreboardGame for all games on the scoreboard.
            Returns empty list on network error.
        """
        if game_date:
            url = f"{NCAA_SCOREBOARD_URL}/{game_date.year}/{game_date.month:02d}/{game_date.day:02d}"
        else:
            url = NCAA_SCOREBOARD_URL
        logger.info("ncaa_scoreboard_fetch", url=url)

        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.error("ncaa_scoreboard_fetch_error", error=str(exc))
            return []

        if response.status_code != 200:
            logger.warning(
                "ncaa_scoreboard_fetch_failed",
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return []

        data = response.json()
        games_data = data.get("games", [])

        logger.info("ncaa_scoreboard_response", game_count=len(games_data))

        results: list[NCAAScoreboardGame] = []
        for game_data in games_data:
            parsed = self._parse_game(game_data)
            if parsed:
                results.append(parsed)

        logger.info(
            "ncaa_scoreboard_parsed",
            total=len(games_data),
            parsed=len(results),
        )
        return results

    def _parse_game(self, game_data: dict) -> NCAAScoreboardGame | None:
        """Parse a single game from the scoreboard response.

        Expected structure:
        {
          "game": {
            "gameID": "6502231",
            "gameState": "live",
            "contestClock": "12:34",
            "currentPeriod": "2",
            "startTimeEpoch": "1708466400",
            "home": {
              "names": {"short": "Purdue", "seo": "purdue"},
              "score": "45"
            },
            "away": {
              "names": {"short": "Indiana", "seo": "indiana"},
              "score": "38"
            }
          }
        }
        """
        game = game_data.get("game", {})
        if not game:
            return None

        game_id = game.get("gameID")
        if not game_id:
            return None

        # Map gameState to normalized status
        raw_state = (game.get("gameState") or "").lower()
        game_state = NCAA_GAME_STATE_MAP.get(raw_state, "scheduled")

        # Extract team info
        home = game.get("home", {})
        away = game.get("away", {})
        home_names = home.get("names", {})
        away_names = away.get("names", {})

        home_team_short = home_names.get("short", "")
        away_team_short = away_names.get("short", "")
        home_team_seo = home_names.get("seo", "")
        away_team_seo = away_names.get("seo", "")

        # Scores are strings in the NCAA API
        home_score = parse_int(home.get("score"))
        away_score = parse_int(away.get("score"))

        current_period = parse_int(game.get("currentPeriod"))
        contest_clock = game.get("contestClock")
        start_time_epoch = parse_int(game.get("startTimeEpoch"))

        return NCAAScoreboardGame(
            ncaa_game_id=str(game_id),
            game_state=game_state,
            home_team_short=home_team_short,
            away_team_short=away_team_short,
            home_team_seo=home_team_seo,
            away_team_seo=away_team_seo,
            home_score=home_score,
            away_score=away_score,
            current_period=current_period,
            contest_clock=contest_clock,
            start_time_epoch=start_time_epoch,
        )
