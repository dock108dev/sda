"""NBA boxscore fetching and parsing.

Handles boxscore data from the NBA CDN API (cdn.nba.com).
"""

from __future__ import annotations

import re

import httpx

from ..logging import logger
from ..models import (
    NormalizedPlayerBoxscore,
    NormalizedTeamBoxscore,
    TeamIdentity,
)
from ..utils.cache import APICache, should_cache_final
from ..utils.parsing import parse_int
from ..utils.provider_request import provider_request
from .nba_constants import NBA_BOXSCORE_URL
from .nba_models import NBABoxscore

# PT clock format used in NBA CDN responses (e.g. "PT36M12.00S")
_CLOCK_PATTERN = re.compile(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")


def _parse_pt_minutes(value: str | None) -> float | None:
    """Parse PT-format duration string into total minutes as a float.

    Examples:
        "PT36M12.00S" -> 36.2
        "PT00M00.00S" -> 0.0
        None -> None
    """
    if not value:
        return None
    match = _CLOCK_PATTERN.match(value)
    if not match:
        return None
    minutes = int(match.group(1) or 0)
    seconds = float(match.group(2) or 0)
    return round(minutes + seconds / 60, 1)


class NBABoxscoreFetcher:
    """Fetches and parses boxscore data from the NBA CDN API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        """Initialize the boxscore fetcher.

        Args:
            client: HTTP client for API requests
            cache: Cache for storing API responses
        """
        self.client = client
        self._cache = cache

    def fetch_boxscore(self, game_id: str) -> NBABoxscore | None:
        """Fetch boxscore from NBA CDN API.

        Results are cached to avoid redundant API calls.

        Args:
            game_id: NBA game ID (e.g., "0022400123")

        Returns:
            NBABoxscore with team and player stats, or None if fetch failed
        """
        # Check cache first
        cache_key = f"boxscore_{game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("nba_boxscore_using_cache", game_id=game_id)
            return self._parse_boxscore_response(cached, game_id)

        url = NBA_BOXSCORE_URL.format(game_id=game_id)
        logger.info("nba_boxscore_fetch", url=url, game_id=game_id)

        try:
            response = provider_request(
                self.client,
                "GET",
                url,
                provider="nba-cdn",
                endpoint="boxscore",
                league="NBA",
                game_id=game_id,
                qps_budget=5.0,
                qps_burst=10,
            )
        except Exception as exc:
            logger.error("nba_boxscore_fetch_error", game_id=game_id, error=str(exc))
            return None

        if response is None:
            return None

        if response.status_code == 403:
            logger.debug("nba_boxscore_blocked", game_id=game_id, status=403)
            return None

        if response.status_code == 404:
            logger.warning("nba_boxscore_not_found", game_id=game_id, status=404)
            return None

        if response.status_code != 200:
            logger.warning(
                "nba_boxscore_fetch_failed",
                game_id=game_id,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return None

        payload = response.json()

        # Only cache final game data — pregame/live data changes constantly
        game = payload.get("game", {})
        game_status = game.get("gameStatus")  # 1=scheduled, 2=live, 3=final
        home_players = game.get("homeTeam", {}).get("players", [])
        away_players = game.get("awayTeam", {}).get("players", [])
        has_data = bool(home_players or away_players)

        if should_cache_final(has_data, game_status):
            self._cache.put(cache_key, payload)
            logger.info("nba_boxscore_cached", game_id=game_id, game_status=game_status)
        else:
            logger.info(
                "nba_boxscore_not_cached",
                game_id=game_id,
                game_status=game_status,
                has_data=has_data,
            )

        return self._parse_boxscore_response(payload, game_id)

    def _parse_boxscore_response(self, payload: dict, game_id: str) -> NBABoxscore:
        """Parse boxscore JSON into normalized structure."""
        game = payload.get("game", {})

        # Map gameStatus: 1=scheduled, 2=live, 3=final
        game_status = game.get("gameStatus")
        if game_status == 3:
            status = "final"
        elif game_status == 2:
            status = "live"
        else:
            status = "scheduled"

        # Extract team data
        home_team_data = game.get("homeTeam", {})
        away_team_data = game.get("awayTeam", {})

        home_tricode = str(home_team_data.get("teamTricode", ""))
        away_tricode = str(away_team_data.get("teamTricode", ""))

        # Use full team names (e.g., "Charlotte Hornets") to match DB records.
        # Tricode-only names ("CHA") cause _upsert_team to create duplicate team records.
        home_name = f"{home_team_data.get('teamCity', '')} {home_team_data.get('teamName', '')}".strip() or home_tricode
        away_name = f"{away_team_data.get('teamCity', '')} {away_team_data.get('teamName', '')}".strip() or away_tricode

        home_team = TeamIdentity(
            league_code="NBA",
            name=home_name,
            abbreviation=home_tricode,
        )
        away_team = TeamIdentity(
            league_code="NBA",
            name=away_name,
            abbreviation=away_tricode,
        )

        home_score = parse_int(home_team_data.get("score")) or 0
        away_score = parse_int(away_team_data.get("score")) or 0

        # Parse player boxscores
        player_boxscores: list[NormalizedPlayerBoxscore] = []

        home_players = self._parse_team_players(home_team_data, home_team, game_id)
        player_boxscores.extend(home_players)

        away_players = self._parse_team_players(away_team_data, away_team, game_id)
        player_boxscores.extend(away_players)

        # Build team boxscores from team-level statistics
        team_boxscores: list[NormalizedTeamBoxscore] = []

        home_team_boxscore = self._build_team_boxscore(
            home_team_data, home_team, is_home=True, score=home_score
        )
        away_team_boxscore = self._build_team_boxscore(
            away_team_data, away_team, is_home=False, score=away_score
        )
        team_boxscores = [away_team_boxscore, home_team_boxscore]

        logger.info(
            "nba_boxscore_parsed",
            game_id=game_id,
            status=status,
            home_score=home_score,
            away_score=away_score,
            home_players=len(home_players),
            away_players=len(away_players),
        )

        return NBABoxscore(
            game_id=game_id,
            game_date=game.get("gameTimeUTC", ""),
            status=status,
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            team_boxscores=team_boxscores,
            player_boxscores=player_boxscores,
        )

    def _parse_team_players(
        self,
        team_data: dict,
        team_identity: TeamIdentity,
        game_id: str,
    ) -> list[NormalizedPlayerBoxscore]:
        """Parse all players for a team from the boxscore response."""
        players: list[NormalizedPlayerBoxscore] = []

        for player_data in team_data.get("players", []):
            player = self._parse_player_stats(player_data, team_identity, game_id)
            if player:
                players.append(player)

        return players

    def _parse_player_stats(
        self,
        player_data: dict,
        team_identity: TeamIdentity,
        game_id: str,
    ) -> NormalizedPlayerBoxscore | None:
        """Parse a single player's stats from the NBA CDN boxscore."""
        person_id = player_data.get("personId")
        if not person_id:
            return None

        player_name = player_data.get("name", "")
        if not player_name:
            logger.warning(
                "nba_boxscore_player_no_name",
                game_id=game_id,
                player_id=person_id,
            )
            return None

        # Skip players who didn't play
        played = player_data.get("played")
        if played == "0":
            return None

        statistics = player_data.get("statistics", {})

        # Parse minutes from PT format
        minutes = _parse_pt_minutes(statistics.get("minutes"))

        # Direct fields on NormalizedPlayerBoxscore
        points = parse_int(statistics.get("points"))
        rebounds = parse_int(statistics.get("reboundsTotal"))
        assists = parse_int(statistics.get("assists"))

        # Shooting and other stats go into raw_stats
        raw_stats: dict = {}
        stat_mappings = {
            "fg_made": "fieldGoalsMade",
            "fg_attempted": "fieldGoalsAttempted",
            "three_made": "threePointersMade",
            "three_attempted": "threePointersAttempted",
            "ft_made": "freeThrowsMade",
            "ft_attempted": "freeThrowsAttempted",
            "offensive_rebounds": "reboundsOffensive",
            "defensive_rebounds": "reboundsDefensive",
            "steals": "steals",
            "blocks": "blocks",
            "turnovers": "turnovers",
            "personal_fouls": "foulsPersonal",
            "plus_minus": "plusMinusPoints",
        }
        for raw_key, api_key in stat_mappings.items():
            val = parse_int(statistics.get(api_key))
            if val is not None:
                raw_stats[raw_key] = val

        return NormalizedPlayerBoxscore(
            player_id=str(person_id),
            player_name=player_name,
            team=team_identity,
            player_role=None,
            position=player_data.get("position"),
            sweater_number=parse_int(player_data.get("jerseyNum")),
            minutes=minutes,
            points=points,
            rebounds=rebounds,
            assists=assists,
            raw_stats=raw_stats,
        )

    def _build_team_boxscore(
        self,
        team_data: dict,
        team_identity: TeamIdentity,
        is_home: bool,
        score: int,
    ) -> NormalizedTeamBoxscore:
        """Build team boxscore from the team-level statistics object."""
        statistics = team_data.get("statistics", {})

        rebounds = parse_int(statistics.get("reboundsTotal"))
        assists = parse_int(statistics.get("assists"))
        turnovers = parse_int(statistics.get("turnovers"))

        # Extract all available team stats from CDN API into raw_stats
        raw_stats: dict = {}
        stat_mappings = {
            "fg_made": "fieldGoalsMade",
            "fg_attempted": "fieldGoalsAttempted",
            "fg_pct": "fieldGoalsPercentage",
            "three_made": "threePointersMade",
            "three_attempted": "threePointersAttempted",
            "three_pct": "threePointersPercentage",
            "ft_made": "freeThrowsMade",
            "ft_attempted": "freeThrowsAttempted",
            "ft_pct": "freeThrowsPercentage",
            "offensive_rebounds": "reboundsOffensive",
            "defensive_rebounds": "reboundsDefensive",
            "steals": "steals",
            "blocks": "blocks",
            "personal_fouls": "foulsPersonal",
            "team_fouls": "foulsTeam",
            "technical_fouls": "foulsTechnical",
            "fast_break_points": "pointsFastBreak",
            "points_in_paint": "pointsInThePaint",
            "points_off_turnovers": "pointsFromTurnovers",
            "second_chance_points": "pointsSecondChance",
            "bench_points": "benchPoints",
            "biggest_lead": "biggestLead",
            "lead_changes": "leadChanges",
            "times_tied": "timesTied",
        }
        for raw_key, api_key in stat_mappings.items():
            val = statistics.get(api_key)
            if val is not None:
                raw_stats[raw_key] = val

        return NormalizedTeamBoxscore(
            team=team_identity,
            is_home=is_home,
            points=score,
            rebounds=rebounds,
            assists=assists,
            turnovers=turnovers,
            raw_stats=raw_stats,
        )
