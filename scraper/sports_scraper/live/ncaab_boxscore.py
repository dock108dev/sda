"""NCAAB boxscore fetching.

Handles fetching boxscore data from the CBB API games/teams and games/players
endpoints. Parsing logic lives in ncaab_boxscore_parser.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import httpx

from ..logging import logger
from ..models import (
    NormalizedPlayerBoxscore,
    NormalizedTeamBoxscore,
)
from ..utils.cache import APICache
from ..utils.datetime_utils import eastern_date_range_to_utc_iso
from .ncaab_boxscore_by_id import NCAABBoxscoreByIdMixin
from .ncaab_boxscore_parser import (
    build_boxscore_from_batch,
    parse_player_stats,
    parse_team_stats,
)
from .ncaab_constants import CBB_GAMES_PLAYERS_URL, CBB_GAMES_TEAMS_URL
from .ncaab_helpers import build_team_identity
from .ncaab_models import NCAABBoxscore, NCAABLiveGame


class NCAABBoxscoreFetcher(NCAABBoxscoreByIdMixin):
    """Fetches and parses boxscore data from the CBB API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        """Initialize the boxscore fetcher.

        Args:
            client: HTTP client for API requests
            cache: Cache for storing API responses
        """
        self.client = client
        self._cache = cache

    def fetch_game_teams_by_date_range(
        self, start_date: date, end_date: date, season: int
    ) -> list[dict]:
        """Fetch team-level boxscore stats for a date range.

        The CBB API ignores the gameId parameter and returns all games (paginated).
        Using date range filtering is more efficient - one API call for many games.
        Results are cached to avoid burning API quota on repeated runs.

        Args:
            start_date: Start of date range
            end_date: End of date range
            season: Season year

        Returns:
            List of team stats dictionaries for all games in the date range
        """
        # Cache completed date ranges — boxscores for past games don't change
        from ..utils.datetime_utils import today_et

        cache_key = f"game_teams_{season}_{start_date}_{end_date}"
        if end_date < today_et():
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        logger.info(
            "ncaab_game_teams_fetch_by_date",
            start_date=str(start_date),
            end_date=str(end_date),
            season=season,
        )

        try:
            # API requires ISO 8601 format in UTC
            start_utc_iso, end_utc_iso = eastern_date_range_to_utc_iso(start_date, end_date)
            params = {
                "season": season,
                "startDateRange": start_utc_iso,
                "endDateRange": end_utc_iso,
            }
            response = self.client.get(CBB_GAMES_TEAMS_URL, params=params)

            if response.status_code != 200:
                logger.warning(
                    "ncaab_game_teams_fetch_failed",
                    start_date=str(start_date),
                    end_date=str(end_date),
                    status=response.status_code,
                    body=response.text[:200] if response.text else "",
                )
                return []

            data = response.json()
            logger.info(
                "ncaab_game_teams_fetched",
                start_date=str(start_date),
                end_date=str(end_date),
                row_count=len(data) if isinstance(data, list) else 1,
            )

            # Cache if date range is in the past
            if end_date < today_et():
                self._cache.put(cache_key, data)

            return data

        except Exception as exc:
            logger.warning(
                "ncaab_game_teams_fetch_error",
                start_date=str(start_date),
                end_date=str(end_date),
                error=str(exc),
            )
            return []

    def fetch_game_players_by_date_range(
        self, start_date: date, end_date: date, season: int
    ) -> list[dict]:
        """Fetch player-level boxscore stats for a date range.

        The CBB API ignores the gameId parameter and returns all games (paginated).
        Using date range filtering is more efficient - one API call for many games.
        Results are cached to avoid burning API quota on repeated runs.

        Args:
            start_date: Start of date range
            end_date: End of date range
            season: Season year

        Returns:
            List of player stats dictionaries for all games in the date range
        """
        from ..utils.datetime_utils import today_et

        cache_key = f"game_players_{season}_{start_date}_{end_date}"
        if end_date < today_et():
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        logger.info(
            "ncaab_game_players_fetch_by_date",
            start_date=str(start_date),
            end_date=str(end_date),
            season=season,
        )

        try:
            # API requires ISO 8601 format in UTC
            start_utc_iso, end_utc_iso = eastern_date_range_to_utc_iso(start_date, end_date)
            params = {
                "season": season,
                "startDateRange": start_utc_iso,
                "endDateRange": end_utc_iso,
            }
            response = self.client.get(CBB_GAMES_PLAYERS_URL, params=params)

            if response.status_code != 200:
                logger.warning(
                    "ncaab_game_players_fetch_failed",
                    start_date=str(start_date),
                    end_date=str(end_date),
                    status=response.status_code,
                    body=response.text[:200] if response.text else "",
                )
                return []

            data = response.json()
            logger.info(
                "ncaab_game_players_fetched",
                start_date=str(start_date),
                end_date=str(end_date),
                row_count=len(data) if isinstance(data, list) else 1,
            )

            if end_date < today_et():
                self._cache.put(cache_key, data)

            return data

        except Exception as exc:
            logger.warning(
                "ncaab_game_players_fetch_error",
                start_date=str(start_date),
                end_date=str(end_date),
                error=str(exc),
            )
            return []

    def fetch_boxscores_batch(
        self,
        game_ids: list[int],
        start_date: date,
        end_date: date,
        season: int,
        team_names_by_game: dict[int, tuple[str, str]],
    ) -> dict[int, NCAABBoxscore]:
        """Fetch boxscores for multiple games in batch API calls.

        Instead of calling the API once per game (which returns all games anyway),
        this method makes just 2 API calls (teams + players) for the entire date range
        and filters the results to the requested game IDs.

        Args:
            game_ids: List of CBB game IDs to fetch boxscores for
            start_date: Start of date range
            end_date: End of date range
            season: Season year
            team_names_by_game: Dict mapping game_id -> (home_team_name, away_team_name)

        Returns:
            Dict mapping game_id -> NCAABBoxscore for successfully fetched games
        """
        logger.info(
            "ncaab_boxscores_batch_fetch",
            game_count=len(game_ids),
            start_date=str(start_date),
            end_date=str(end_date),
            season=season,
        )

        # Convert to set for fast lookup
        game_id_set = set(game_ids)

        # Fetch all team stats for date range (1 API call)
        all_team_stats = self.fetch_game_teams_by_date_range(start_date, end_date, season)

        # Fetch all player stats for date range (1 API call)
        all_player_stats = self.fetch_game_players_by_date_range(start_date, end_date, season)

        # Group team stats by gameId
        team_stats_by_game: dict[int, list[dict]] = defaultdict(list)
        for ts in all_team_stats:
            gid = ts.get("gameId")
            if gid and int(gid) in game_id_set:
                team_stats_by_game[int(gid)].append(ts)

        # Group player stats by gameId
        player_stats_by_game: dict[int, list[dict]] = defaultdict(list)
        for ps in all_player_stats:
            gid = ps.get("gameId")
            if gid and int(gid) in game_id_set:
                player_stats_by_game[int(gid)].append(ps)

        logger.info(
            "ncaab_boxscores_batch_grouped",
            requested_games=len(game_ids),
            games_with_team_stats=len(team_stats_by_game),
            games_with_player_stats=len(player_stats_by_game),
        )

        # Build boxscores for requested game_ids
        results: dict[int, NCAABBoxscore] = {}
        for gid in game_ids:
            team_stats = team_stats_by_game.get(gid, [])
            if not team_stats:
                # No team stats found for this game
                continue

            player_stats = player_stats_by_game.get(gid, [])
            team_names = team_names_by_game.get(gid)
            if not team_names:
                continue

            home_team_name, away_team_name = team_names

            boxscore = build_boxscore_from_batch(
                gid, team_stats, player_stats, home_team_name, away_team_name, season
            )
            if boxscore:
                results[gid] = boxscore

        logger.info(
            "ncaab_boxscores_batch_complete",
            requested_games=len(game_ids),
            boxscores_built=len(results),
        )

        return results

    def fetch_game_teams(self, game_id: int, season: int) -> list[dict]:
        """Fetch team-level boxscore stats for a game.

        Note: The API returns all games in the response regardless of gameId filter.
        For bulk operations, prefer fetch_boxscores_batch() for efficiency.
        """
        logger.info("ncaab_game_teams_fetch", game_id=game_id, season=season)

        try:
            params = {"gameId": game_id, "season": season}
            response = self.client.get(CBB_GAMES_TEAMS_URL, params=params)

            if response.status_code != 200:
                logger.warning(
                    "ncaab_game_teams_fetch_failed",
                    game_id=game_id,
                    status=response.status_code,
                    body=response.text[:200] if response.text else "",
                )
                return []

            data = response.json()
            if data:
                sample = data[0] if isinstance(data, list) else data
                logger.info(
                    "ncaab_game_teams_response_sample",
                    game_id=game_id,
                    row_count=len(data) if isinstance(data, list) else 1,
                    sample_keys=list(sample.keys()) if isinstance(sample, dict) else str(type(sample)),
                )
            return data

        except Exception as exc:
            logger.warning(
                "ncaab_game_teams_fetch_error",
                game_id=game_id,
                error=str(exc),
            )
            return []

    def fetch_game_players(self, game_id: int, season: int) -> list[dict]:
        """Fetch player-level boxscore stats for a game.

        Note: The API returns all games in the response regardless of gameId filter.
        For bulk operations, prefer fetch_boxscores_batch() for efficiency.
        """
        logger.info("ncaab_game_players_fetch", game_id=game_id, season=season)

        try:
            params = {"gameId": game_id, "season": season}
            response = self.client.get(CBB_GAMES_PLAYERS_URL, params=params)

            if response.status_code != 200:
                logger.warning(
                    "ncaab_game_players_fetch_failed",
                    game_id=game_id,
                    status=response.status_code,
                    body=response.text[:200] if response.text else "",
                )
                return []

            data = response.json()
            if data:
                sample = data[0] if isinstance(data, list) else data
                logger.info(
                    "ncaab_game_players_response_sample",
                    game_id=game_id,
                    row_count=len(data) if isinstance(data, list) else 1,
                    sample_keys=list(sample.keys()) if isinstance(sample, dict) else str(type(sample)),
                )
            return data

        except Exception as exc:
            logger.warning(
                "ncaab_game_players_fetch_error",
                game_id=game_id,
                error=str(exc),
            )
            return []

    def fetch_boxscore(self, game: NCAABLiveGame) -> NCAABBoxscore | None:
        """Fetch full boxscore for a game."""
        logger.info("ncaab_boxscore_fetch", game_id=game.game_id, season=game.season)

        # Fetch team stats
        team_stats = self.fetch_game_teams(game.game_id, game.season)
        if not team_stats:
            logger.warning("ncaab_boxscore_no_team_stats", game_id=game.game_id)
            return None

        # Fetch player stats
        player_stats = self.fetch_game_players(game.game_id, game.season)

        # Build team identities
        home_team = build_team_identity(game.home_team_name, game.home_team_id)
        away_team = build_team_identity(game.away_team_name, game.away_team_id)

        # Parse team boxscores
        team_boxscores: list[NormalizedTeamBoxscore] = []
        home_score = game.home_score or 0
        away_score = game.away_score or 0

        for ts in team_stats:
            team_id = ts.get("teamId")
            is_home = team_id == game.home_team_id
            team_identity = home_team if is_home else away_team
            score = home_score if is_home else away_score

            team_boxscore = parse_team_stats(ts, team_identity, is_home, score)
            team_boxscores.append(team_boxscore)

        # Parse player boxscores
        player_boxscores: list[NormalizedPlayerBoxscore] = []
        for ps in player_stats:
            team_id = ps.get("teamId")
            is_home = team_id == game.home_team_id
            team_identity = home_team if is_home else away_team

            player_boxscore = parse_player_stats(ps, team_identity, game.game_id)
            if player_boxscore:
                player_boxscores.append(player_boxscore)

        logger.info(
            "ncaab_boxscore_parsed",
            game_id=game.game_id,
            status=game.status,
            home_score=home_score,
            away_score=away_score,
            home_players=len([p for p in player_boxscores if p.team.name == home_team.name]),
            away_players=len([p for p in player_boxscores if p.team.name == away_team.name]),
        )

        return NCAABBoxscore(
            game_id=game.game_id,
            game_date=game.game_date,
            status=game.status,
            season=game.season,
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            team_boxscores=team_boxscores,
            player_boxscores=player_boxscores,
        )
