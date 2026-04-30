"""NHL boxscore fetching and parsing.

Handles boxscore data from the NHL API (api-web.nhle.com).
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
from ..utils.provider_request import provider_request
from .nhl_constants import NHL_BOXSCORE_URL
from .nhl_helpers import (
    build_team_identity_from_api,
    map_nhl_game_state,
    parse_datetime,
    parse_save_shots,
    parse_toi_to_minutes,
)
from .nhl_models import NHLBoxscore


class NHLBoxscoreFetcher:
    """Fetches and parses boxscore data from the NHL API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        """Initialize the boxscore fetcher.

        Args:
            client: HTTP client for API requests
            cache: Cache for storing API responses
        """
        self.client = client
        self._cache = cache

    def fetch_boxscore(self, game_id: int) -> NHLBoxscore | None:
        """Fetch boxscore from NHL API.

        Results are cached to avoid redundant API calls.

        Args:
            game_id: NHL game ID (e.g., 2025020767)

        Returns:
            NHLBoxscore with team and player stats, or None if fetch failed
        """
        # Check cache first
        cache_key = f"boxscore_{game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("nhl_boxscore_using_cache", game_id=game_id)
            return self._parse_boxscore_response(cached, game_id)

        url = NHL_BOXSCORE_URL.format(game_id=game_id)
        logger.info("nhl_boxscore_fetch", url=url, game_id=game_id)

        try:
            response = provider_request(
                self.client,
                "GET",
                url,
                provider="nhl-api",
                endpoint="boxscore",
                league="NHL",
                game_id=game_id,
                qps_budget=5.0,
                qps_burst=10,
            )
        except Exception as exc:
            logger.error("nhl_boxscore_fetch_error", game_id=game_id, error=str(exc))
            return None

        if response is None:
            return None

        if response.status_code == 404:
            logger.warning("nhl_boxscore_not_found", game_id=game_id, status=404)
            return None

        if response.status_code != 200:
            logger.warning(
                "nhl_boxscore_fetch_failed",
                game_id=game_id,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return None

        payload = response.json()

        # Only cache final game data — pregame/live data changes constantly
        game_state = payload.get("gameState", "")
        player_stats = payload.get("playerByGameStats", {})
        has_data = bool(
            player_stats.get("homeTeam", {}).get("forwards")
            or player_stats.get("homeTeam", {}).get("defense")
            or player_stats.get("homeTeam", {}).get("goalies")
        )

        if should_cache_final(has_data, game_state):
            self._cache.put(cache_key, payload)
            logger.info("nhl_boxscore_cached", game_id=game_id, game_state=game_state)
        else:
            logger.info(
                "nhl_boxscore_not_cached",
                game_id=game_id,
                game_state=game_state,
                has_data=has_data,
            )

        return self._parse_boxscore_response(payload, game_id)

    def _parse_boxscore_response(self, payload: dict, game_id: int) -> NHLBoxscore:
        """Parse boxscore JSON into normalized structure."""
        # Extract game info
        game_date_str = payload.get("gameDate", "")
        game_date = parse_datetime(game_date_str + "T00:00:00Z")
        game_state = payload.get("gameState", "")
        status = map_nhl_game_state(game_state)

        # Extract team info
        home_team_data = payload.get("homeTeam", {})
        away_team_data = payload.get("awayTeam", {})

        home_team = build_team_identity_from_api(home_team_data)
        away_team = build_team_identity_from_api(away_team_data)

        home_score = parse_int(home_team_data.get("score")) or 0
        away_score = parse_int(away_team_data.get("score")) or 0

        # Extract team-level stats
        team_boxscores: list[NormalizedTeamBoxscore] = []
        player_boxscores: list[NormalizedPlayerBoxscore] = []

        # Parse player stats for each team
        player_by_game_stats = payload.get("playerByGameStats", {})

        # Home team players
        home_players_data = player_by_game_stats.get("homeTeam", {})
        home_players = self._parse_team_players(home_players_data, home_team, game_id)
        player_boxscores.extend(home_players)

        # Away team players
        away_players_data = player_by_game_stats.get("awayTeam", {})
        away_players = self._parse_team_players(away_players_data, away_team, game_id)
        player_boxscores.extend(away_players)

        # Build team boxscores from aggregated player stats
        home_team_boxscore = self._build_team_boxscore_from_players(
            home_team, is_home=True, score=home_score, players=home_players
        )
        away_team_boxscore = self._build_team_boxscore_from_players(
            away_team, is_home=False, score=away_score, players=away_players
        )
        team_boxscores = [away_team_boxscore, home_team_boxscore]

        logger.info(
            "nhl_boxscore_parsed",
            game_id=game_id,
            status=status,
            home_score=home_score,
            away_score=away_score,
            home_players=len([p for p in player_boxscores if p.team.abbreviation == home_team.abbreviation]),
            away_players=len([p for p in player_boxscores if p.team.abbreviation == away_team.abbreviation]),
        )

        return NHLBoxscore(
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

    def _parse_team_players(
        self,
        team_data: dict,
        team_identity: TeamIdentity,
        game_id: int,
    ) -> list[NormalizedPlayerBoxscore]:
        """Parse all players for a team from playerByGameStats."""
        players: list[NormalizedPlayerBoxscore] = []

        # Parse forwards
        for player_data in team_data.get("forwards", []):
            player = self._parse_skater_stats(player_data, team_identity, game_id)
            if player:
                players.append(player)

        # Parse defense
        for player_data in team_data.get("defense", []):
            player = self._parse_skater_stats(player_data, team_identity, game_id)
            if player:
                players.append(player)

        # Parse goalies
        for player_data in team_data.get("goalies", []):
            player = self._parse_goalie_stats(player_data, team_identity, game_id)
            if player:
                players.append(player)

        return players

    def _parse_skater_stats(
        self,
        player_data: dict,
        team_identity: TeamIdentity,
        game_id: int,
    ) -> NormalizedPlayerBoxscore | None:
        """Parse skater stats (forwards/defense) from NHL API."""
        player_id = player_data.get("playerId")
        if not player_id:
            return None

        name_data = player_data.get("name", {})
        player_name = name_data.get("default", "")
        if not player_name:
            logger.warning(
                "nhl_boxscore_player_no_name",
                game_id=game_id,
                player_id=player_id,
            )
            return None

        # Parse time on ice
        toi = player_data.get("toi", "")
        minutes = parse_toi_to_minutes(toi)

        # Parse faceoff percentage
        faceoff_pct = player_data.get("faceoffWinningPctg")
        if faceoff_pct is not None:
            faceoff_pct = round(float(faceoff_pct) * 100, 1) if faceoff_pct else None

        # Build raw stats
        raw_stats = {
            "powerPlayGoals": player_data.get("powerPlayGoals"),
            "shorthandedGoals": player_data.get("shorthandedGoals"),
        }
        raw_stats = {k: v for k, v in raw_stats.items() if v is not None}

        return NormalizedPlayerBoxscore(
            player_id=str(player_id),
            player_name=player_name,
            team=team_identity,
            player_role="skater",
            position=player_data.get("position"),
            sweater_number=parse_int(player_data.get("sweaterNumber")),
            minutes=minutes,
            goals=parse_int(player_data.get("goals")),
            assists=parse_int(player_data.get("assists")),
            points=parse_int(player_data.get("points")),
            shots_on_goal=parse_int(player_data.get("sog")),
            penalties=parse_int(player_data.get("pim")),
            plus_minus=parse_int(player_data.get("plusMinus")),
            hits=parse_int(player_data.get("hits")),
            blocked_shots=parse_int(player_data.get("blockedShots")),
            shifts=parse_int(player_data.get("shifts")),
            giveaways=parse_int(player_data.get("giveaways")),
            takeaways=parse_int(player_data.get("takeaways")),
            faceoff_pct=faceoff_pct,
            saves=None,
            goals_against=None,
            shots_against=None,
            save_percentage=None,
            raw_stats=raw_stats,
        )

    def _parse_goalie_stats(
        self,
        player_data: dict,
        team_identity: TeamIdentity,
        game_id: int,
    ) -> NormalizedPlayerBoxscore | None:
        """Parse goalie stats from NHL API."""
        player_id = player_data.get("playerId")
        if not player_id:
            return None

        name_data = player_data.get("name", {})
        player_name = name_data.get("default", "")
        if not player_name:
            logger.warning(
                "nhl_boxscore_goalie_no_name",
                game_id=game_id,
                player_id=player_id,
            )
            return None

        # Parse time on ice
        toi = player_data.get("toi", "")
        minutes = parse_toi_to_minutes(toi)

        # Parse saveShotsAgainst
        save_shots = player_data.get("saveShotsAgainst", "")
        saves, shots_against = parse_save_shots(save_shots)

        # Get goals against and save percentage
        goals_against = parse_int(player_data.get("goalsAgainst"))
        save_pctg = player_data.get("savePctg")
        # Store as decimal (0.935), not percentage (93.5) — frontend formats
        save_percentage = round(float(save_pctg), 4) if save_pctg is not None else None

        # Build raw stats
        raw_stats = {
            "evenStrengthShotsAgainst": player_data.get("evenStrengthShotsAgainst"),
            "powerPlayShotsAgainst": player_data.get("powerPlayShotsAgainst"),
            "shorthandedShotsAgainst": player_data.get("shorthandedShotsAgainst"),
        }
        raw_stats = {k: v for k, v in raw_stats.items() if v is not None}

        return NormalizedPlayerBoxscore(
            player_id=str(player_id),
            player_name=player_name,
            team=team_identity,
            player_role="goalie",
            position="G",
            sweater_number=parse_int(player_data.get("sweaterNumber")),
            minutes=minutes,
            saves=saves,
            goals_against=goals_against,
            shots_against=shots_against,
            save_percentage=save_percentage,
            goals=None,
            assists=None,
            points=None,
            shots_on_goal=None,
            penalties=parse_int(player_data.get("pim")),
            plus_minus=None,
            hits=None,
            blocked_shots=None,
            shifts=None,
            giveaways=None,
            takeaways=None,
            faceoff_pct=None,
            raw_stats=raw_stats,
        )

    def _build_team_boxscore_from_players(
        self,
        team_identity: TeamIdentity,
        is_home: bool,
        score: int,
        players: list[NormalizedPlayerBoxscore],
    ) -> NormalizedTeamBoxscore:
        """Build team boxscore by aggregating player stats."""
        skaters = [p for p in players if p.player_role == "skater"]

        total_shots = sum(p.shots_on_goal or 0 for p in skaters)
        total_pim = sum(p.penalties or 0 for p in skaters)
        total_assists = sum(p.assists or 0 for p in skaters)
        total_goals = sum(p.goals or 0 for p in skaters)
        total_hits = sum(p.hits or 0 for p in skaters)
        total_blocked = sum(p.blocked_shots or 0 for p in skaters)
        total_giveaways = sum(p.giveaways or 0 for p in skaters)
        total_takeaways = sum(p.takeaways or 0 for p in skaters)

        raw_stats = {
            "goals": total_goals,
            "assists": total_assists,
            "shots_on_goal": total_shots,
            "penalty_minutes": total_pim,
            "hits": total_hits,
            "blocked_shots": total_blocked,
            "giveaways": total_giveaways,
            "takeaways": total_takeaways,
        }

        return NormalizedTeamBoxscore(
            team=team_identity,
            is_home=is_home,
            points=score,
            shots_on_goal=total_shots if total_shots > 0 else None,
            penalty_minutes=total_pim if total_pim > 0 else None,
            assists=total_assists if total_assists > 0 else None,
            raw_stats=raw_stats,
        )
