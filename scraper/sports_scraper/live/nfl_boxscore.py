"""NFL boxscore fetching and parsing.

Handles boxscore data from the ESPN NFL summary API.
The summary endpoint includes both PBP and boxscore data in a single response.
"""

from __future__ import annotations

import httpx

from ..logging import logger
from ..models import (
    NormalizedPlayerBoxscore,
    NormalizedTeamBoxscore,
    TeamIdentity,
)
from ..utils.cache import APICache, should_cache_final
from ..utils.parsing import parse_int
from .nfl_constants import NFL_STATUS_MAP, NFL_SUMMARY_URL
from .nfl_helpers import build_team_identity_from_espn, parse_espn_datetime
from .nfl_models import NFLBoxscore


class NFLBoxscoreFetcher:
    """Fetches and parses boxscore data from the ESPN NFL summary API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        self.client = client
        self._cache = cache

    def fetch_boxscore(self, game_id: int) -> NFLBoxscore | None:
        """Fetch boxscore from ESPN summary API."""
        cache_key = f"boxscore_{game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("nfl_boxscore_using_cache", game_id=game_id)
            return self._parse_boxscore_response(cached, game_id)

        url = NFL_SUMMARY_URL.format(game_id=game_id)
        logger.info("nfl_boxscore_fetch", url=url, game_id=game_id)

        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.error("nfl_boxscore_fetch_error", game_id=game_id, error=str(exc))
            return None

        if response.status_code == 404:
            logger.warning("nfl_boxscore_not_found", game_id=game_id, status=404)
            return None

        if response.status_code != 200:
            logger.warning(
                "nfl_boxscore_fetch_failed",
                game_id=game_id,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return None

        payload = response.json()

        # Cache if final
        game_status = self._extract_game_status(payload)
        is_final = game_status in ("final", "cancelled")
        boxscore_data = payload.get("boxscore", {})
        has_data = bool(boxscore_data.get("players"))
        if should_cache_final(has_data, "OFF" if is_final else "LIVE"):
            self._cache.put(cache_key, payload)
            logger.info("nfl_boxscore_cached", game_id=game_id)

        return self._parse_boxscore_response(payload, game_id)

    def _extract_game_status(self, payload: dict) -> str:
        """Extract normalized game status from ESPN summary payload."""
        header = payload.get("header", {})
        competitions = header.get("competitions", [])
        if competitions:
            status_type = competitions[0].get("status", {}).get("type", {}).get("name", "")
            return NFL_STATUS_MAP.get(status_type, "scheduled")
        return "scheduled"

    def _parse_boxscore_response(self, payload: dict, game_id: int) -> NFLBoxscore | None:
        """Parse ESPN summary response into NFLBoxscore."""
        header = payload.get("header", {})
        competitions = header.get("competitions", [])
        if not competitions:
            logger.warning("nfl_boxscore_no_competitions", game_id=game_id)
            return None

        competition = competitions[0]

        # Extract game date
        game_date_str = competition.get("date")
        game_date = parse_espn_datetime(game_date_str)

        # Status
        status_type = competition.get("status", {}).get("type", {}).get("name", "")
        status = NFL_STATUS_MAP.get(status_type, "scheduled")

        # Extract teams from competitors
        competitors = competition.get("competitors", [])
        home_team_data = None
        away_team_data = None
        home_score = 0
        away_score = 0

        for comp in competitors:
            team_info = comp.get("team", {})
            if comp.get("homeAway") == "home":
                home_team_data = team_info
                home_score = parse_int(comp.get("score")) or 0
            else:
                away_team_data = team_info
                away_score = parse_int(comp.get("score")) or 0

        if not home_team_data or not away_team_data:
            logger.warning("nfl_boxscore_missing_teams", game_id=game_id)
            return None

        home_team = build_team_identity_from_espn(home_team_data)
        away_team = build_team_identity_from_espn(away_team_data)

        # Parse boxscore section
        boxscore_data = payload.get("boxscore", {})
        team_boxscores: list[NormalizedTeamBoxscore] = []
        player_boxscores: list[NormalizedPlayerBoxscore] = []

        # Team stats from boxscore.teams[]
        teams_stats = boxscore_data.get("teams", [])
        for team_stat in teams_stats:
            team_info = team_stat.get("team", {})
            team_identity = build_team_identity_from_espn(team_info)
            is_home = team_identity.abbreviation == home_team.abbreviation
            team_bs = self._parse_team_stats(
                team_stat, team_identity, is_home,
                home_score if is_home else away_score,
            )
            team_boxscores.append(team_bs)

        # Player stats from boxscore.players[]
        players_data = boxscore_data.get("players", [])
        for team_players in players_data:
            team_info = team_players.get("team", {})
            team_identity = build_team_identity_from_espn(team_info)
            for category in team_players.get("statistics", []):
                category_name = category.get("name", "")
                labels = category.get("labels", [])
                for athlete_data in category.get("athletes", []):
                    player = self._parse_player_stats(
                        athlete_data, team_identity, category_name, labels, game_id,
                    )
                    if player:
                        player_boxscores.append(player)

        logger.info(
            "nfl_boxscore_parsed",
            game_id=game_id,
            status=status,
            home_score=home_score,
            away_score=away_score,
            players=len(player_boxscores),
        )

        return NFLBoxscore(
            game_id=game_id,
            game_date=game_date,
            status=status,
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            team_boxscores=team_boxscores,
            player_boxscores=player_boxscores,
        )

    def _parse_team_stats(
        self,
        team_stat: dict,
        team_identity: TeamIdentity,
        is_home: bool,
        score: int,
    ) -> NormalizedTeamBoxscore:
        """Parse team-level stats from ESPN boxscore."""
        raw_stats: dict = {}
        for stat_group in team_stat.get("statistics", []):
            stat_name = stat_group.get("name", "")
            stat_value = stat_group.get("displayValue", "")
            raw_stats[stat_name] = stat_value

        return NormalizedTeamBoxscore(
            team=team_identity,
            is_home=is_home,
            points=score,
            raw_stats=raw_stats,
        )

    def _parse_player_stats(
        self,
        athlete_data: dict,
        team_identity: TeamIdentity,
        category_name: str,
        labels: list[str],
        game_id: int,
    ) -> NormalizedPlayerBoxscore | None:
        """Parse player stats from ESPN boxscore."""
        athlete = athlete_data.get("athlete", {})
        player_id = athlete.get("id")
        player_name = athlete.get("displayName", "")

        if not player_id or not player_name:
            return None

        stats_values = athlete_data.get("stats", [])
        # Build a dict from labels + values
        raw_stats: dict = {"category": category_name}
        for i, label in enumerate(labels):
            if i < len(stats_values):
                raw_stats[label] = stats_values[i]

        return NormalizedPlayerBoxscore(
            player_id=str(player_id),
            player_name=player_name,
            team=team_identity,
            player_role=category_name.lower(),
            position=athlete.get("position", {}).get("abbreviation"),
            raw_stats=raw_stats,
        )
