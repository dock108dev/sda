"""NCAAB boxscore parsing and building.

Stateless functions for parsing team and player stats from CBB API responses
and assembling NCAABBoxscore objects from pre-fetched data.
"""

from __future__ import annotations

from ..logging import logger
from ..models import (
    NormalizedPlayerBoxscore,
    NormalizedTeamBoxscore,
    TeamIdentity,
)
from ..utils.datetime_utils import now_utc
from ..utils.math import parse_minutes
from ..utils.parsing import parse_int
from .ncaab_helpers import (
    build_team_identity,
    extract_points,
    extract_shooting_stat,
    extract_total,
)
from .ncaab_models import NCAABBoxscore


def parse_team_stats(
    ts: dict,
    team_identity: TeamIdentity,
    is_home: bool,
    score: int,
) -> NormalizedTeamBoxscore:
    """Parse team-level stats from games/teams endpoint.

    The CBB API can return stats nested under "teamStats" or flat at the
    top level.  Either way, strip metadata keys so only actual stat fields
    end up in raw_stats.
    """
    # Prefer the nested teamStats sub-object; fall back to top-level dict
    stats = ts.get("teamStats", {}) or {}
    if not stats:
        # Flat format — filter out metadata keys that are not stats
        _METADATA_KEYS = {
            "teamId", "gameId", "isHome", "season", "team", "conference",
            "opponent", "opponentId", "opponentConference",
        }
        stats = {k: v for k, v in ts.items() if v is not None and k not in _METADATA_KEYS}

    return NormalizedTeamBoxscore(
        team=team_identity,
        is_home=is_home,
        points=score,
        rebounds=parse_int(stats.get("totalRebounds")) or parse_int(stats.get("rebounds")),
        assists=parse_int(stats.get("assists")),
        turnovers=parse_int(stats.get("turnovers")),
        raw_stats={k: v for k, v in stats.items() if v is not None},
    )


def parse_player_stats(
    ps: dict,
    team_identity: TeamIdentity,
    game_id: int,
) -> NormalizedPlayerBoxscore | None:
    """Parse player-level stats from games/players endpoint.

    The CBB API can return stats as either:
    - Simple integers: {"points": 17, "rebounds": 5}
    - Nested objects: {"points": {"total": 17}, "rebounds": {"total": 5, "offensive": 2}}

    This handles both formats.
    """
    player_id = ps.get("playerId") or ps.get("athleteId")
    if not player_id:
        return None

    player_name = ps.get("name") or ps.get("player") or ps.get("athleteName") or ""
    if not player_name:
        logger.warning(
            "ncaab_boxscore_player_no_name",
            game_id=game_id,
            player_id=player_id,
        )
        return None

    minutes = parse_minutes(ps.get("minutes"))

    # Extract stats handling both flat and nested formats
    points = extract_total(ps.get("points"))
    rebounds = extract_total(ps.get("rebounds")) or extract_total(ps.get("totalRebounds"))
    assists = extract_total(ps.get("assists"))
    steals = extract_total(ps.get("steals"))
    blocks = extract_total(ps.get("blocks"))
    turnovers = extract_total(ps.get("turnovers"))

    # Shooting stats (flat key -> nested key.sub_key)
    fg_made = extract_shooting_stat(ps, "fieldGoalsMade", "fieldGoals", "made")
    fg_att = extract_shooting_stat(ps, "fieldGoalsAttempted", "fieldGoals", "attempted")
    fg3_made = extract_shooting_stat(ps, "threePointFieldGoalsMade", "threePointFieldGoals", "made")
    fg3_att = extract_shooting_stat(ps, "threePointFieldGoalsAttempted", "threePointFieldGoals", "attempted")
    ft_made = extract_shooting_stat(ps, "freeThrowsMade", "freeThrows", "made")
    ft_att = extract_shooting_stat(ps, "freeThrowsAttempted", "freeThrows", "attempted")
    fouls = extract_total(ps.get("fouls")) or extract_total(ps.get("personalFouls"))

    # Build raw_stats with flattened values for display
    _METADATA_KEYS = {"playerId", "athleteId", "player", "athleteName", "name", "teamId", "team", "minutes"}
    raw_stats = {k: v for k, v in ps.items() if v is not None and k not in _METADATA_KEYS}

    # Overlay flattened shooting / counting stats for frontend display
    _FLAT_STATS: dict[str, int | None] = {
        "fgMade": fg_made, "fgAttempted": fg_att,
        "fg3Made": fg3_made, "fg3Attempted": fg3_att,
        "ftMade": ft_made, "ftAttempted": ft_att,
        "steals": steals, "blocks": blocks,
        "turnovers": turnovers, "fouls": fouls,
    }
    for key, val in _FLAT_STATS.items():
        if val is not None:
            raw_stats[key] = val

    return NormalizedPlayerBoxscore(
        player_id=str(player_id),
        player_name=player_name,
        team=team_identity,
        player_role=None,
        position=ps.get("position"),
        sweater_number=None,
        minutes=minutes,
        points=points,
        rebounds=rebounds,
        assists=assists,
        raw_stats=raw_stats,
    )


def build_boxscore_from_batch(
    game_id: int,
    team_stats: list[dict],
    player_stats: list[dict],
    home_team_name: str,
    away_team_name: str,
    season: int,
) -> NCAABBoxscore | None:
    """Build a boxscore from pre-fetched team and player stats."""
    # Parse team stats to determine home/away and extract scores
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
        points = extract_points(stats.get("points"))

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
        "ncaab_boxscore_built_from_batch",
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
        game_date=now_utc(),  # Will be overwritten with actual date in ingestion
        status="final",
        season=season,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        team_boxscores=team_boxscores,
        player_boxscores=player_boxscores,
    )
