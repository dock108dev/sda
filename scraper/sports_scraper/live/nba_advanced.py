"""NBA advanced stats fetcher (stats.nba.com endpoints).

Fetches boxscoreadvancedv3, boxscorehustlev2, and boxscoreplayertrackingv3
for a given NBA game and returns raw JSON for downstream ingestion.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import settings
from ..logging import logger
from ..utils.cache import APICache, should_cache_final


class NBAAdvancedStatsFetcher:
    """Fetches advanced stats from stats.nba.com endpoints."""

    def __init__(self) -> None:
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nba.com/",
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true",
            "Origin": "https://www.nba.com",
        }
        self._base_url = "https://stats.nba.com/stats"
        self._timeout = 10  # Short timeout — stats.nba.com blocks cloud IPs
        self._delay = 2.0  # seconds between API calls to be a good citizen
        cache_dir = settings.scraper_config.html_cache_dir
        self._cache = APICache(cache_dir=cache_dir, api_name="nba_advanced")
        self._client = httpx.Client(timeout=self._timeout, headers=self._headers)

    # ------------------------------------------------------------------
    # Public fetch methods
    # ------------------------------------------------------------------

    def fetch_advanced_boxscore(self, nba_game_id: str) -> dict | None:
        """Fetch boxscoreadvancedv3 for a game.

        Returns raw JSON response or None on failure.
        """
        cache_key = f"nba_advanced_{nba_game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("nba_advanced_boxscore_cache_hit", game_id=nba_game_id)
            return cached

        url = f"{self._base_url}/boxscoreadvancedv3"
        params = {"GameID": nba_game_id}
        data = self._fetch(url, params, "boxscoreadvancedv3", nba_game_id)

        if data is not None:
            has_data = bool(
                data.get("boxScoreAdvanced")
                or _find_result_set(data, "PlayerStats")
                or _find_result_set(data, "TeamStats")
            )
            if should_cache_final(has_data, "final"):
                self._cache.put(cache_key, data)

        return data

    def fetch_hustle_stats(self, nba_game_id: str) -> dict | None:
        """Fetch boxscorehustlev2 for a game.

        Returns raw JSON response or None on failure.
        """
        cache_key = f"nba_hustle_{nba_game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("nba_hustle_cache_hit", game_id=nba_game_id)
            return cached

        time.sleep(self._delay)
        url = f"{self._base_url}/boxscorehustlev2"
        params = {"GameID": nba_game_id}
        data = self._fetch(url, params, "boxscorehustlev2", nba_game_id)

        if data is not None:
            has_data = bool(
                data.get("resultSets")
                or data.get("boxScoreHustle")
            )
            if should_cache_final(has_data, "final"):
                self._cache.put(cache_key, data)

        return data

    def fetch_tracking_stats(self, nba_game_id: str) -> dict | None:
        """Fetch boxscoreplayertrackingv3 for a game.

        Returns raw JSON response or None on failure.
        """
        cache_key = f"nba_tracking_{nba_game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("nba_tracking_cache_hit", game_id=nba_game_id)
            return cached

        time.sleep(self._delay)
        url = f"{self._base_url}/boxscoreplayertrackingv3"
        params = {"GameID": nba_game_id}
        data = self._fetch(url, params, "boxscoreplayertrackingv3", nba_game_id)

        if data is not None:
            has_data = bool(
                data.get("resultSets")
                or data.get("boxScorePlayerTrack")
            )
            if should_cache_final(has_data, "final"):
                self._cache.put(cache_key, data)

        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch(
        self,
        url: str,
        params: dict[str, str],
        endpoint_name: str,
        nba_game_id: str,
    ) -> dict | None:
        """Execute an HTTP GET with error handling for stats.nba.com quirks."""
        logger.info(
            "nba_advanced_fetch",
            endpoint=endpoint_name,
            game_id=nba_game_id,
            url=url,
        )
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException:
            logger.warning(
                "nba_advanced_fetch_timeout",
                endpoint=endpoint_name,
                game_id=nba_game_id,
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning(
                "nba_advanced_fetch_error",
                endpoint=endpoint_name,
                game_id=nba_game_id,
                error=str(exc),
            )
            return None

        if response.status_code in (403, 429):
            logger.warning(
                "nba_advanced_rate_limited",
                endpoint=endpoint_name,
                game_id=nba_game_id,
                status=response.status_code,
            )
            return None

        if response.status_code >= 500:
            logger.warning(
                "nba_advanced_server_error",
                endpoint=endpoint_name,
                game_id=nba_game_id,
                status=response.status_code,
            )
            return None

        if response.status_code != 200:
            logger.warning(
                "nba_advanced_unexpected_status",
                endpoint=endpoint_name,
                game_id=nba_game_id,
                status=response.status_code,
            )
            return None

        try:
            return response.json()
        except Exception as exc:
            logger.warning(
                "nba_advanced_json_parse_error",
                endpoint=endpoint_name,
                game_id=nba_game_id,
                error=str(exc),
            )
            return None


# ------------------------------------------------------------------
# Parsing helpers
# ------------------------------------------------------------------


def _find_result_set(data: dict, set_name: str) -> dict | None:
    """Find a named resultSet in the stats.nba.com response format."""
    for rs in data.get("resultSets", []):
        if rs.get("name") == set_name:
            return rs
    return None


def _parse_result_set(data: dict, set_name: str) -> list[dict[str, Any]]:
    """Convert a stats.nba.com resultSet (headers + rowSet) into a list of dicts.

    The stats.nba.com JSON format is:
    {
      "resultSets": [
        {
          "name": "PlayerStats",
          "headers": ["GAME_ID", "TEAM_ID", "PLAYER_ID", ...],
          "rowSet": [[val1, val2, ...], ...]
        }
      ]
    }

    Returns an empty list if the set_name is not found.
    """
    rs = _find_result_set(data, set_name)
    if rs is None:
        return []

    headers = rs.get("headers", [])
    rows = rs.get("rowSet", [])
    return [dict(zip(headers, row, strict=False)) for row in rows]


def parse_advanced_boxscore(data: dict) -> tuple[list[dict], list[dict]]:
    """Parse boxscoreadvancedv3 response into (team_rows, player_rows).

    Handles both the legacy resultSets format and the newer boxScoreAdvanced format.
    """
    # Try newer nested format first (boxScoreAdvanced)
    box = data.get("boxScoreAdvanced")
    if box:
        team_rows = []
        player_rows = []

        # Team stats from nested format
        home_team = box.get("homeTeam", {})
        away_team = box.get("awayTeam", {})
        for team_data, is_home in [(home_team, True), (away_team, False)]:
            stats = team_data.get("statistics", {})
            team_rows.append({
                "TEAM_ID": team_data.get("teamId"),
                "TEAM_ABBREVIATION": team_data.get("teamTricode"),
                "is_home": is_home,
                "E_OFF_RATING": stats.get("estimatedOffensiveRating"),
                "OFF_RATING": stats.get("offensiveRating"),
                "E_DEF_RATING": stats.get("estimatedDefensiveRating"),
                "DEF_RATING": stats.get("defensiveRating"),
                "E_NET_RATING": stats.get("estimatedNetRating"),
                "NET_RATING": stats.get("netRating"),
                "PACE": stats.get("pace"),
                "PIE": stats.get("pie"),
                "EFG_PCT": stats.get("effectiveFieldGoalPercentage"),
                "TS_PCT": stats.get("trueShootingPercentage"),
                "AST_PCT": stats.get("assistPercentage"),
                "AST_RATIO": stats.get("assistRatio"),
                "AST_TOV": stats.get("assistToTurnover"),
                "TM_TOV_PCT": stats.get("turnoverPercentage"),
                "OREB_PCT": stats.get("offensiveReboundPercentage"),
                "DREB_PCT": stats.get("defensiveReboundPercentage"),
                "REB_PCT": stats.get("reboundPercentage"),
            })

            # Player stats from nested format
            for player in team_data.get("players", []):
                p_stats = player.get("statistics", {})
                player_rows.append({
                    "TEAM_ID": team_data.get("teamId"),
                    "PLAYER_ID": player.get("personId"),
                    "PLAYER_NAME": f"{player.get('firstName', '')} {player.get('familyName', '')}".strip(),
                    "is_home": is_home,
                    "MIN": p_stats.get("minutes"),
                    "OFF_RATING": p_stats.get("offensiveRating"),
                    "DEF_RATING": p_stats.get("defensiveRating"),
                    "NET_RATING": p_stats.get("netRating"),
                    "USG_PCT": p_stats.get("usagePercentage"),
                    "PIE": p_stats.get("pie"),
                    "TS_PCT": p_stats.get("trueShootingPercentage"),
                    "EFG_PCT": p_stats.get("effectiveFieldGoalPercentage"),
                })

        return team_rows, player_rows

    # Fall back to legacy resultSets format
    team_rows = _parse_result_set(data, "TeamStats")
    player_rows = _parse_result_set(data, "PlayerStats")
    return team_rows, player_rows


def parse_hustle_stats(data: dict) -> list[dict]:
    """Parse boxscorehustlev2 response into player hustle rows.

    Handles both the resultSets format and newer boxScoreHustle format.
    """
    # Try newer nested format
    box = data.get("boxScoreHustle")
    if box:
        rows = []
        home_team = box.get("homeTeam", {})
        away_team = box.get("awayTeam", {})
        for team_data, is_home in [(home_team, True), (away_team, False)]:
            for player in team_data.get("players", []):
                stats = player.get("statistics", {})
                rows.append({
                    "TEAM_ID": team_data.get("teamId"),
                    "PLAYER_ID": player.get("personId"),
                    "PLAYER_NAME": f"{player.get('firstName', '')} {player.get('familyName', '')}".strip(),
                    "is_home": is_home,
                    "CONTESTED_SHOTS": stats.get("contestedShots"),
                    "DEFLECTIONS": stats.get("deflections"),
                    "CHARGES_DRAWN": stats.get("chargesDrawn"),
                    "LOOSE_BALLS_RECOVERED": stats.get("looseBallsRecovered"),
                    "SCREEN_ASSISTS": stats.get("screenAssists"),
                })
        return rows

    # Fall back to resultSets format
    return _parse_result_set(data, "PlayerStats")


def parse_tracking_stats(data: dict) -> list[dict]:
    """Parse boxscoreplayertrackingv3 response into player tracking rows.

    Handles both the resultSets format and newer boxScorePlayerTrack format.
    """
    # Try newer nested format
    box = data.get("boxScorePlayerTrack")
    if box:
        rows = []
        home_team = box.get("homeTeam", {})
        away_team = box.get("awayTeam", {})
        for team_data, is_home in [(home_team, True), (away_team, False)]:
            for player in team_data.get("players", []):
                stats = player.get("statistics", {})
                rows.append({
                    "TEAM_ID": team_data.get("teamId"),
                    "PLAYER_ID": player.get("personId"),
                    "PLAYER_NAME": f"{player.get('firstName', '')} {player.get('familyName', '')}".strip(),
                    "is_home": is_home,
                    "SPD": stats.get("speed"),
                    "DIST": stats.get("distance"),
                    "TCHS": stats.get("touches"),
                    "TIME_OF_POSS": stats.get("possessionTime"),
                    "CONT_2PT_FGA": stats.get("contested2ptShots"),
                    "CONT_2PT_FGM": None,  # Not always available
                    "UCONT_2PT_FGA": stats.get("uncontested2ptShots"),
                    "UCONT_2PT_FGM": None,
                    "CONT_3PT_FGA": stats.get("contested3ptShots"),
                    "CONT_3PT_FGM": None,
                    "UCONT_3PT_FGA": stats.get("uncontested3ptShots"),
                    "UCONT_3PT_FGM": None,
                    "PULL_UP_FGA": stats.get("pullUpFga"),
                    "PULL_UP_FGM": stats.get("pullUpFgm"),
                    "CATCH_SHOOT_FGA": stats.get("catchShootFga"),
                    "CATCH_SHOOT_FGM": stats.get("catchShootFgm"),
                })
        return rows

    # Fall back to resultSets format
    return _parse_result_set(data, "PlayerStats")
