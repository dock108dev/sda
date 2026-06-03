"""Direct-by-ID NCAAB boxscore fetch path."""

from __future__ import annotations

from datetime import datetime

from ..logging import logger
from ..models import NormalizedPlayerBoxscore, NormalizedTeamBoxscore
from .ncaab_boxscore_parser import parse_player_stats, parse_team_stats
from .ncaab_helpers import build_team_identity
from .ncaab_models import NCAABBoxscore


class NCAABBoxscoreByIdMixin:
    def fetch_boxscore_by_id(
        self,
        game_id: int,
        season: int,
        game_date: datetime,
        home_team_name: str,
        away_team_name: str,
    ) -> NCAABBoxscore | None:
        """Fetch boxscore directly by game ID without needing full game info."""
        logger.info("ncaab_boxscore_fetch_by_id", game_id=game_id, season=season)

        # Fetch team stats - API returns ALL games, we need to filter
        all_team_stats = self.fetch_game_teams(game_id, season)
        if not all_team_stats:
            logger.warning("ncaab_boxscore_no_team_stats", game_id=game_id)
            return None

        # Filter to only rows for this specific game
        target_game_id = int(game_id)
        team_stats = [ts for ts in all_team_stats if int(ts.get("gameId", 0)) == target_game_id]

        if not team_stats:
            sample_ids = [ts.get("gameId") for ts in all_team_stats[:10]]
            logger.warning(
                "ncaab_boxscore_game_not_in_response",
                game_id=game_id,
                total_rows=len(all_team_stats),
                sample_game_ids=sample_ids,
            )
            return None

        logger.info("ncaab_boxscore_filtered", game_id=game_id, matched_rows=len(team_stats))

        # Fetch player stats - also returns ALL games
        all_player_stats = self.fetch_game_players(game_id, season)
        player_stats = [ps for ps in all_player_stats if int(ps.get("gameId", 0)) == target_game_id]

        # Extract team info from team stats
        home_team_id = None
        away_team_id = None
        home_score = 0
        away_score = 0
        home_team_stats_raw = None
        away_team_stats_raw = None

        for ts in team_stats:
            team_id = ts.get("teamId")
            is_home = ts.get("isHome", False)
            stats = ts.get("teamStats", {}) or {}
            points = stats.get("points", 0) or 0

            if is_home:
                home_team_id = team_id
                home_score = points
                home_team_stats_raw = ts
            else:
                away_team_id = team_id
                away_score = points
                away_team_stats_raw = ts

        # Build team identities using DB team names
        home_team = build_team_identity(home_team_name, home_team_id or 0)
        away_team = build_team_identity(away_team_name, away_team_id or 0)

        # Parse team boxscores
        team_boxscores: list[NormalizedTeamBoxscore] = []
        if home_team_stats_raw:
            team_boxscore = parse_team_stats(
                home_team_stats_raw, home_team, True, home_score
            )
            team_boxscores.append(team_boxscore)
        if away_team_stats_raw:
            team_boxscore = parse_team_stats(
                away_team_stats_raw, away_team, False, away_score
            )
            team_boxscores.append(team_boxscore)

        # Parse player boxscores from nested "players" array
        player_boxscores: list[NormalizedPlayerBoxscore] = []
        for ps in player_stats:
            team_id = ps.get("teamId")
            is_home = team_id == home_team_id
            team_identity = home_team if is_home else away_team

            players_list = ps.get("players", []) or []
            for player in players_list:
                player_boxscore = parse_player_stats(player, team_identity, game_id)
                if player_boxscore:
                    player_boxscores.append(player_boxscore)

        logger.info(
            "ncaab_boxscore_parsed_by_id",
            game_id=game_id,
            home_team=home_team_name,
            away_team=away_team_name,
            home_score=home_score,
            away_score=away_score,
            team_stats_count=len(team_boxscores),
            player_stats_count=len(player_boxscores),
        )

        return NCAABBoxscore(
            game_id=game_id,
            game_date=game_date,
            status="final",
            season=season,
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            team_boxscores=team_boxscores,
            player_boxscores=player_boxscores,
        )
