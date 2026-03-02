"""MLB boxscore fetching and parsing.

Handles boxscore data from the MLB Stats API (statsapi.mlb.com).
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
from .mlb_constants import MLB_BOXSCORE_URL
from .mlb_helpers import build_team_identity_from_api
from .mlb_models import MLBBoxscore


class MLBBoxscoreFetcher:
    """Fetches and parses boxscore data from the MLB Stats API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        self.client = client
        self._cache = cache

    def fetch_boxscore(
        self, game_pk: int, game_status: str | None = None
    ) -> MLBBoxscore | None:
        """Fetch boxscore from MLB Stats API.

        Args:
            game_pk: MLB game primary key.
            game_status: Normalized game status from the DB (e.g. "final").
                Used by should_cache_final to decide whether to persist the
                response.  When None the response is never cached.

        Results are cached to avoid redundant API calls.
        """
        cache_key = f"mlb_boxscore_{game_pk}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("mlb_boxscore_using_cache", game_pk=game_pk)
            return self._parse_boxscore_response(cached, game_pk, game_status)

        url = MLB_BOXSCORE_URL.format(game_pk=game_pk)
        logger.info("mlb_boxscore_fetch", url=url, game_pk=game_pk)

        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.error("mlb_boxscore_fetch_error", game_pk=game_pk, error=str(exc))
            return None

        if response.status_code == 404:
            logger.warning("mlb_boxscore_not_found", game_pk=game_pk, status=404)
            return None

        if response.status_code != 200:
            logger.warning(
                "mlb_boxscore_fetch_failed",
                game_pk=game_pk,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return None

        payload = response.json()

        # Only cache final game data — the boxscore endpoint doesn't include
        # gameState, so the caller must pass the real status from the DB.
        teams = payload.get("teams", {})
        has_data = bool(
            teams.get("home", {}).get("players")
            or teams.get("away", {}).get("players")
        )

        if should_cache_final(has_data, game_status):
            self._cache.put(cache_key, payload)
            logger.info("mlb_boxscore_cached", game_pk=game_pk, game_status=game_status)
        else:
            logger.info("mlb_boxscore_not_cached", game_pk=game_pk, has_data=has_data, game_status=game_status)

        return self._parse_boxscore_response(payload, game_pk, game_status)

    def _parse_boxscore_response(
        self, payload: dict, game_pk: int, game_status: str | None = None
    ) -> MLBBoxscore:
        """Parse boxscore JSON into normalized structure."""
        teams = payload.get("teams", {})
        home_data = teams.get("home", {})
        away_data = teams.get("away", {})

        home_team = build_team_identity_from_api(home_data)
        away_team = build_team_identity_from_api(away_data)

        # Extract scores from teamStats
        home_stats = home_data.get("teamStats", {}).get("batting", {})
        away_stats = away_data.get("teamStats", {}).get("batting", {})
        home_score = parse_int(home_stats.get("runs")) or 0
        away_score = parse_int(away_stats.get("runs")) or 0

        team_boxscores: list[NormalizedTeamBoxscore] = []
        player_boxscores: list[NormalizedPlayerBoxscore] = []

        # Parse player stats for each team
        home_players = self._parse_team_players(home_data, home_team, game_pk)
        away_players = self._parse_team_players(away_data, away_team, game_pk)
        player_boxscores.extend(home_players)
        player_boxscores.extend(away_players)

        # Build team boxscores from team-level stats
        home_team_boxscore = self._build_team_boxscore(
            home_data, home_team, is_home=True, score=home_score
        )
        away_team_boxscore = self._build_team_boxscore(
            away_data, away_team, is_home=False, score=away_score
        )
        team_boxscores = [away_team_boxscore, home_team_boxscore]

        logger.info(
            "mlb_boxscore_parsed",
            game_pk=game_pk,
            home_score=home_score,
            away_score=away_score,
            home_players=len(home_players),
            away_players=len(away_players),
        )

        return MLBBoxscore(
            game_pk=game_pk,
            status=game_status or "scheduled",
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
        game_pk: int,
    ) -> list[NormalizedPlayerBoxscore]:
        """Parse all players for a team from the boxscore."""
        players: list[NormalizedPlayerBoxscore] = []

        players_dict = team_data.get("players", {})
        batters = set(team_data.get("batters", []))
        pitchers = set(team_data.get("pitchers", []))

        for _player_key, player_data in players_dict.items():
            person = player_data.get("person", {})
            player_id = person.get("id")
            if not player_id:
                continue

            player_name = person.get("fullName", "")
            if not player_name:
                continue

            position = player_data.get("position", {}).get("abbreviation", "")
            jersey = parse_int(player_data.get("jerseyNumber"))

            stats = player_data.get("stats", {})

            # Parse batting stats if player batted
            if player_id in batters:
                batting = stats.get("batting", {})
                if batting:
                    player = self._parse_batter_stats(
                        player_id, player_name, position, jersey,
                        batting, team_identity, game_pk,
                    )
                    if player:
                        players.append(player)

            # Parse pitching stats if player pitched
            if player_id in pitchers:
                pitching = stats.get("pitching", {})
                if pitching:
                    player = self._parse_pitcher_stats(
                        player_id, player_name, position, jersey,
                        pitching, team_identity, game_pk,
                    )
                    if player:
                        players.append(player)

        return players

    def _parse_batter_stats(
        self,
        player_id: int,
        player_name: str,
        position: str,
        jersey: int | None,
        batting: dict,
        team_identity: TeamIdentity,
        game_pk: int,
    ) -> NormalizedPlayerBoxscore | None:
        """Parse batter stats from MLB API."""
        raw_stats = {
            "player_role": "batter",
            "atBats": parse_int(batting.get("atBats")),
            "hits": parse_int(batting.get("hits")),
            "runs": parse_int(batting.get("runs")),
            "rbi": parse_int(batting.get("rbi")),
            "homeRuns": parse_int(batting.get("homeRuns")),
            "baseOnBalls": parse_int(batting.get("baseOnBalls")),
            "strikeOuts": parse_int(batting.get("strikeOuts")),
            "doubles": parse_int(batting.get("doubles")),
            "triples": parse_int(batting.get("triples")),
            "stolenBases": parse_int(batting.get("stolenBases")),
            "caughtStealing": parse_int(batting.get("caughtStealing")),
            "avg": batting.get("avg"),
            "obp": batting.get("obp"),
            "slg": batting.get("slg"),
            "ops": batting.get("ops"),
            "leftOnBase": parse_int(batting.get("leftOnBase")),
            "sacBunts": parse_int(batting.get("sacBunts")),
            "sacFlies": parse_int(batting.get("sacFlies")),
            "groundIntoDoublePlay": parse_int(batting.get("groundIntoDoublePlay")),
        }
        raw_stats = {k: v for k, v in raw_stats.items() if v is not None}

        return NormalizedPlayerBoxscore(
            player_id=str(player_id),
            player_name=player_name,
            team=team_identity,
            player_role="batter",
            position=position,
            sweater_number=jersey,
            minutes=None,
            goals=parse_int(batting.get("runs")),
            assists=parse_int(batting.get("rbi")),
            points=parse_int(batting.get("hits")),
            shots_on_goal=parse_int(batting.get("atBats")),
            penalties=None,
            plus_minus=None,
            hits=parse_int(batting.get("hits")),
            blocked_shots=None,
            shifts=None,
            giveaways=None,
            takeaways=None,
            faceoff_pct=None,
            saves=None,
            goals_against=None,
            shots_against=None,
            save_percentage=None,
            raw_stats=raw_stats,
        )

    def _parse_pitcher_stats(
        self,
        player_id: int,
        player_name: str,
        position: str,
        jersey: int | None,
        pitching: dict,
        team_identity: TeamIdentity,
        game_pk: int,
    ) -> NormalizedPlayerBoxscore | None:
        """Parse pitcher stats from MLB API."""
        raw_stats = {
            "player_role": "pitcher",
            "inningsPitched": pitching.get("inningsPitched"),
            "hits": parse_int(pitching.get("hits")),
            "runs": parse_int(pitching.get("runs")),
            "earnedRuns": parse_int(pitching.get("earnedRuns")),
            "baseOnBalls": parse_int(pitching.get("baseOnBalls")),
            "strikeOuts": parse_int(pitching.get("strikeOuts")),
            "homeRuns": parse_int(pitching.get("homeRuns")),
            "era": pitching.get("era"),
            "whip": pitching.get("whip"),
            "pitchCount": parse_int(pitching.get("numberOfPitches")),
            "strikes": parse_int(pitching.get("strikes")),
            "balls": parse_int(pitching.get("balls")),
            "battersFaced": parse_int(pitching.get("battersFaced")),
            "outs": parse_int(pitching.get("outs")),
            "hitBatsmen": parse_int(pitching.get("hitBatsmen")),
            "wildPitches": parse_int(pitching.get("wildPitches")),
            "stolenBases": parse_int(pitching.get("stolenBases")),
            "wins": parse_int(pitching.get("wins")),
            "losses": parse_int(pitching.get("losses")),
            "saves_stat": parse_int(pitching.get("saves")),
            "holds": parse_int(pitching.get("holds")),
            "blownSaves": parse_int(pitching.get("blownSaves")),
        }
        raw_stats = {k: v for k, v in raw_stats.items() if v is not None}

        return NormalizedPlayerBoxscore(
            player_id=str(player_id),
            player_name=player_name,
            team=team_identity,
            player_role="pitcher",
            position=position or "P",
            sweater_number=jersey,
            minutes=None,
            goals=None,
            assists=None,
            points=None,
            shots_on_goal=None,
            penalties=None,
            plus_minus=None,
            hits=None,
            blocked_shots=None,
            shifts=None,
            giveaways=None,
            takeaways=None,
            faceoff_pct=None,
            saves=None,
            goals_against=None,
            shots_against=None,
            save_percentage=None,
            raw_stats=raw_stats,
        )

    def _build_team_boxscore(
        self,
        team_data: dict,
        team_identity: TeamIdentity,
        is_home: bool,
        score: int,
    ) -> NormalizedTeamBoxscore:
        """Build team boxscore from team-level stats."""
        team_stats = team_data.get("teamStats", {})
        batting = team_stats.get("batting", {})
        pitching = team_stats.get("pitching", {})
        fielding = team_stats.get("fielding", {})

        raw_stats = {
            "batting": {k: v for k, v in batting.items() if v is not None},
            "pitching": {k: v for k, v in pitching.items() if v is not None},
            "fielding": {k: v for k, v in fielding.items() if v is not None},
        }

        return NormalizedTeamBoxscore(
            team=team_identity,
            is_home=is_home,
            points=score,
            hits=parse_int(batting.get("hits")),
            raw_stats=raw_stats,
        )
