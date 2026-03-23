"""NCAA API boxscore fetching and parsing.

Fetches per-game boxscore data from the NCAA API (ncaa-api.henrygd.me) and
produces the same NCAABBoxscore dataclass used by the CBB API fetcher, so
downstream persistence code needs no changes.
"""

from __future__ import annotations

import httpx

from ..logging import logger
from ..models import NormalizedPlayerBoxscore, NormalizedTeamBoxscore
from ..utils.cache import APICache, should_cache_final
from ..utils.datetime_utils import now_utc
from ..utils.parsing import parse_int
from .ncaa_constants import NCAA_BOXSCORE_URL
from .ncaab_helpers import build_team_identity, parse_minutes
from .ncaab_models import NCAABBoxscore


class NCAABoxscoreFetcher:
    """Fetches and parses boxscore data from the NCAA API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        self.client = client
        self._cache = cache

    def fetch_boxscore(
        self,
        ncaa_game_id: str,
        home_team_name: str,
        away_team_name: str,
        game_status: str | None = None,
    ) -> NCAABBoxscore | None:
        """Fetch boxscore for a single game from the NCAA API.

        Args:
            ncaa_game_id: NCAA game ID (string)
            home_team_name: Canonical home team name for identity building
            away_team_name: Canonical away team name for identity building
            game_status: Normalized game status from the DB (e.g. "final")

        Returns:
            NCAABBoxscore or None if data unavailable
        """
        cache_key = f"ncaa_boxscore_{ncaa_game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("ncaa_boxscore_using_cache", ncaa_game_id=ncaa_game_id)
            return self._parse_response(cached, ncaa_game_id, home_team_name, away_team_name)

        url = NCAA_BOXSCORE_URL.format(game_id=ncaa_game_id)
        logger.info("ncaa_boxscore_fetch", url=url, ncaa_game_id=ncaa_game_id)

        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.error("ncaa_boxscore_fetch_error", ncaa_game_id=ncaa_game_id, error=str(exc))
            return None

        if response.status_code == 404:
            logger.warning("ncaa_boxscore_not_found", ncaa_game_id=ncaa_game_id, status=404)
            return None

        if response.status_code != 200:
            logger.warning(
                "ncaa_boxscore_fetch_failed",
                ncaa_game_id=ncaa_game_id,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return None

        payload = response.json()
        boxscore = self._parse_response(payload, ncaa_game_id, home_team_name, away_team_name)

        # Cache final game data
        has_data = boxscore is not None and bool(boxscore.team_boxscores)
        if should_cache_final(has_data, game_status):
            self._cache.put(cache_key, payload)
            logger.info("ncaa_boxscore_cached", ncaa_game_id=ncaa_game_id)

        return boxscore

    def _parse_response(
        self,
        payload: dict,
        ncaa_game_id: str,
        home_team_name: str,
        away_team_name: str,
    ) -> NCAABBoxscore | None:
        """Parse the NCAA boxscore API response.

        Actual API structure (ncaa-api.henrygd.me):
        {
          "teams": [
            {
              "isHome": true,
              "teamId": "123",
              "nameShort": "PUR"
            },
            {
              "isHome": false,
              "teamId": "456",
              "nameShort": "IND"
            }
          ],
          "teamBoxscore": [
            {
              "teamStats": {
                "fieldGoalsMade": "25", "fieldGoalsAttempted": "55",
                "totalRebounds": "35", "assists": "15", "turnovers": "10",
                "steals": "5", "blockedShots": "3", "personalFouls": "18",
                "points": "72"
              },
              "playerStats": [
                {
                  "id": 12345, "firstName": "Zach", "lastName": "Edey",
                  "position": "C", "starter": true,
                  "minutesPlayed": "32:00", "points": "25",
                  "rebounds": "12", "assists": "1", "steals": "0",
                  "blockedShots": "3", "turnovers": "2", "personalFouls": "3",
                  "fieldGoalsMade": "10", "fieldGoalsAttempted": "15",
                  "threePointsMade": "0", "threePointsAttempted": "0",
                  "freeThrowsMade": "5", "freeThrowsAttempted": "7"
                }
              ]
            },
            ...
          ]
        }

        teams[] and teamBoxscore[] share the same order. Home/away is
        determined by the isHome boolean on each teams[] entry.
        """
        # teams[] has metadata (isHome, teamId, nameShort)
        teams_meta = payload.get("teams", [])
        # teamBoxscore[] has stats (teamStats, playerStats) in same order
        team_boxscore_data = payload.get("teamBoxscore", [])

        if not teams_meta or len(teams_meta) < 2:
            logger.warning("ncaa_boxscore_no_teams", ncaa_game_id=ncaa_game_id)
            return None

        if not team_boxscore_data or len(team_boxscore_data) < 2:
            logger.warning("ncaa_boxscore_no_stats", ncaa_game_id=ncaa_game_id)
            return None

        # Build home/away map from teams metadata using isHome boolean
        home_idx: int | None = None
        away_idx: int | None = None
        for i, team_meta in enumerate(teams_meta):
            if team_meta.get("isHome") is True:
                home_idx = i
            else:
                away_idx = i

        if home_idx is None or away_idx is None:
            logger.warning(
                "ncaa_boxscore_no_home_away",
                ncaa_game_id=ncaa_game_id,
                teams_meta=teams_meta,
            )
            return None

        home_stats_data = team_boxscore_data[home_idx]
        away_stats_data = team_boxscore_data[away_idx]

        # Build team identities
        home_team = build_team_identity(home_team_name, 0)
        away_team = build_team_identity(away_team_name, 0)

        # Parse team stats from teamStats dict
        team_boxscores: list[NormalizedTeamBoxscore] = []
        home_score = 0
        away_score = 0

        home_totals = home_stats_data.get("teamStats", {})
        if home_totals:
            home_score = parse_int(home_totals.get("points")) or 0
            team_boxscores.append(
                self._parse_team_stats(home_totals, home_team, True, home_score)
            )

        away_totals = away_stats_data.get("teamStats", {})
        if away_totals:
            away_score = parse_int(away_totals.get("points")) or 0
            team_boxscores.append(
                self._parse_team_stats(away_totals, away_team, False, away_score)
            )

        # Parse player stats from playerStats array
        player_boxscores: list[NormalizedPlayerBoxscore] = []

        for player in home_stats_data.get("playerStats", []):
            parsed = self._parse_player_stats(player, home_team, ncaa_game_id)
            if parsed:
                player_boxscores.append(parsed)

        for player in away_stats_data.get("playerStats", []):
            parsed = self._parse_player_stats(player, away_team, ncaa_game_id)
            if parsed:
                player_boxscores.append(parsed)

        logger.info(
            "ncaa_boxscore_parsed",
            ncaa_game_id=ncaa_game_id,
            home_team=home_team_name,
            away_team=away_team_name,
            home_score=home_score,
            away_score=away_score,
            team_stats=len(team_boxscores),
            player_stats=len(player_boxscores),
        )

        return NCAABBoxscore(
            game_id=int(ncaa_game_id) if ncaa_game_id.isdigit() else 0,
            game_date=now_utc(),
            status="final",
            season=0,  # Caller will set the correct season
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            team_boxscores=team_boxscores,
            player_boxscores=player_boxscores,
        )

    def _parse_team_stats(
        self,
        totals: dict,
        team_identity: NormalizedTeamBoxscore | object,
        is_home: bool,
        score: int,
    ) -> NormalizedTeamBoxscore:
        """Parse team-level totals from NCAA API playerTotals."""
        # All values are strings in NCAA API
        raw_stats: dict = {}
        for key, val in totals.items():
            if val is not None:
                raw_stats[key] = val

        return NormalizedTeamBoxscore(
            team=team_identity,  # type: ignore[arg-type]
            is_home=is_home,
            points=score,
            rebounds=parse_int(totals.get("totalRebounds")),
            assists=parse_int(totals.get("assists")),
            turnovers=parse_int(totals.get("turnovers")),
            raw_stats=raw_stats,
        )

    def _parse_player_stats(
        self,
        player: dict,
        team_identity: object,
        game_id: str,
    ) -> NormalizedPlayerBoxscore | None:
        """Parse a single player's boxscore from the NCAA API.

        All stat values come as strings from the NCAA API.
        """
        player_id = player.get("id")
        if player_id is None:
            return None

        first_name = player.get("firstName") or ""
        last_name = player.get("lastName") or ""
        player_name = f"{first_name} {last_name}".strip()
        if not player_name:
            logger.warning(
                "ncaa_boxscore_player_no_name",
                ncaa_game_id=game_id,
                player_id=player_id,
            )
            return None

        minutes = parse_minutes(player.get("minutesPlayed"))
        points = parse_int(player.get("points"))
        rebounds = parse_int(player.get("rebounds")) or parse_int(player.get("totalRebounds"))
        assists = parse_int(player.get("assists"))
        steals = parse_int(player.get("steals"))
        blocks = parse_int(player.get("blockedShots")) or parse_int(player.get("blocks"))
        turnovers = parse_int(player.get("turnovers"))
        fouls = parse_int(player.get("personalFouls")) or parse_int(player.get("fouls"))

        # Shooting stats
        fg_made = parse_int(player.get("fieldGoalsMade"))
        fg_att = parse_int(player.get("fieldGoalsAttempted"))
        fg3_made = parse_int(player.get("threePointsMade")) or parse_int(player.get("threePointFieldGoalsMade"))
        fg3_att = parse_int(player.get("threePointsAttempted")) or parse_int(player.get("threePointFieldGoalsAttempted"))
        ft_made = parse_int(player.get("freeThrowsMade"))
        ft_att = parse_int(player.get("freeThrowsAttempted"))

        # Build raw_stats
        raw_stats: dict = {k: v for k, v in player.items() if v is not None and k not in {
            "id", "firstName", "lastName", "position", "starter", "minutesPlayed",
        }}

        # Add flattened shooting stats for frontend display
        if fg_made is not None or fg_att is not None:
            raw_stats["fgMade"] = fg_made
            raw_stats["fgAttempted"] = fg_att
        if fg3_made is not None or fg3_att is not None:
            raw_stats["fg3Made"] = fg3_made
            raw_stats["fg3Attempted"] = fg3_att
        if ft_made is not None or ft_att is not None:
            raw_stats["ftMade"] = ft_made
            raw_stats["ftAttempted"] = ft_att
        if steals is not None:
            raw_stats["steals"] = steals
        if blocks is not None:
            raw_stats["blocks"] = blocks
        if turnovers is not None:
            raw_stats["turnovers"] = turnovers
        if fouls is not None:
            raw_stats["fouls"] = fouls

        return NormalizedPlayerBoxscore(
            player_id=str(player_id),
            player_name=player_name,
            team=team_identity,  # type: ignore[arg-type]
            player_role=None,
            position=player.get("position"),
            sweater_number=None,
            minutes=minutes,
            points=points,
            rebounds=rebounds,
            assists=assists,
            raw_stats=raw_stats,
        )
