"""NCAAB four-factor advanced stats computation.

Computes tempo-free four-factor analytics from CBB API boxscore data
already stored in the database. No new external API calls needed --
all metrics are derived from existing team and player boxscore JSONB.

Four factors (Dean Oliver):
- eFG%: effective field goal percentage
- TOV%: turnover percentage
- ORB%: offensive rebound percentage
- FT Rate: free throw rate (FTA/FGA)

College uses 0.475 FTA coefficient (vs 0.44 for NBA) in possession
and turnover-rate formulas.
"""

from __future__ import annotations

from ..logging import logger

# College basketball constants
FTA_COEFF = 0.475  # college possession coefficient (0.44 for NBA)
REGULATION_MINUTES = 40  # 40-minute games (not 48 like NBA)
STANDARD_TEAM_MINUTES = 200  # 5 players * 40 minutes


from ..utils.math import safe_div as _safe_div  # noqa: E402


def _extract_stat(box: dict, key: str, default: int = 0) -> int:
    """Extract an integer stat from boxscore JSONB, defaulting to 0.

    Handles both flat keys (e.g., "fieldGoalsMade") and nested
    CBB API format (e.g., {"fieldGoals": {"made": 25}}).
    """
    # Try flat key first (legacy / some sources)
    val = box.get(key)
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    # Map common flat keys → nested CBB API paths
    nested_map = {
        "fieldGoalsMade": ("fieldGoals", "made"),
        "fieldGoalsAttempted": ("fieldGoals", "attempted"),
        "threePointsMade": ("threePointFieldGoals", "made"),
        "threePointsAttempted": ("threePointFieldGoals", "attempted"),
        "freeThrowsMade": ("freeThrows", "made"),
        "freeThrowsAttempted": ("freeThrows", "attempted"),
        "offensiveRebounds": ("rebounds", "offensive"),
        "defensiveRebounds": ("rebounds", "defensive"),
        "turnovers": ("turnovers", "total"),
        "points": ("points", "total"),
    }

    path = nested_map.get(key)
    if path:
        parent = box.get(path[0])
        if isinstance(parent, dict):
            val = parent.get(path[1])
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return default

    return default


def _extract_float_stat(box: dict, key: str, default: float = 0.0) -> float:
    """Extract a float stat from boxscore JSONB."""
    val = box.get(key, default)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _compute_possessions(fga: int, orb: int, tov: int, fta: int) -> float:
    """Compute possessions: FGA - ORB + TOV + 0.475 * FTA."""
    return fga - orb + tov + FTA_COEFF * fta


def _compute_team_four_factors(box: dict, opp_box: dict) -> dict:
    """Compute four-factor stats for one team given its boxscore and opponent's.

    Args:
        box: Team boxscore stats JSONB dict.
        opp_box: Opponent boxscore stats JSONB dict.

    Returns:
        Dict with all computed advanced stats for this team.
    """
    # Extract raw stats -- team offense
    fgm = _extract_stat(box, "fieldGoalsMade")
    fga = _extract_stat(box, "fieldGoalsAttempted")
    tpm = _extract_stat(box, "threePointsMade")
    tpa = _extract_stat(box, "threePointsAttempted")
    ftm = _extract_stat(box, "freeThrowsMade")
    fta = _extract_stat(box, "freeThrowsAttempted")
    orb = _extract_stat(box, "offensiveRebounds")
    drb = _extract_stat(box, "defensiveRebounds")
    tov = _extract_stat(box, "turnovers")
    pts = _extract_stat(box, "points")

    # Extract raw stats -- opponent offense (our defense)
    opp_fgm = _extract_stat(opp_box, "fieldGoalsMade")
    opp_fga = _extract_stat(opp_box, "fieldGoalsAttempted")
    opp_tpm = _extract_stat(opp_box, "threePointsMade")
    opp_fta = _extract_stat(opp_box, "freeThrowsAttempted")
    opp_orb = _extract_stat(opp_box, "offensiveRebounds")
    opp_drb = _extract_stat(opp_box, "defensiveRebounds")
    opp_tov = _extract_stat(opp_box, "turnovers")
    opp_pts = _extract_stat(opp_box, "points")

    # Possessions
    poss = _compute_possessions(fga, orb, tov, fta)
    opp_poss = _compute_possessions(opp_fga, opp_orb, opp_tov, opp_fta)

    # Efficiency ratings (points per 100 possessions)
    off_rating = _safe_div(pts * 100, poss) if poss > 0 else None
    def_rating = _safe_div(opp_pts * 100, poss) if poss > 0 else None
    net_rating = (off_rating - def_rating) if off_rating is not None and def_rating is not None else None

    # Pace: possessions per 40 minutes
    # Use average of team/opp possessions, normalize to 40 minutes
    avg_poss = (poss + opp_poss) / 2 if (poss + opp_poss) > 0 else 0
    pace = avg_poss * REGULATION_MINUTES / (STANDARD_TEAM_MINUTES / 5) if avg_poss > 0 else None

    # Four factors -- offense
    off_efg_pct = _safe_div(fgm + 0.5 * tpm, fga)
    off_tov_pct = _safe_div(tov, fga + FTA_COEFF * fta + tov) if (fga + FTA_COEFF * fta + tov) > 0 else None
    off_orb_pct = _safe_div(orb, orb + opp_drb)
    off_ft_rate = _safe_div(fta, fga)

    # Four factors -- defense (opponent's offensive numbers)
    def_efg_pct = _safe_div(opp_fgm + 0.5 * opp_tpm, opp_fga)
    def_tov_pct = _safe_div(opp_tov, opp_fga + FTA_COEFF * opp_fta + opp_tov) if (opp_fga + FTA_COEFF * opp_fta + opp_tov) > 0 else None
    def_orb_pct = _safe_div(opp_orb, opp_orb + drb)
    def_ft_rate = _safe_div(opp_fta, opp_fga)

    # Shooting splits
    fg_pct = _safe_div(fgm, fga)
    three_pt_pct = _safe_div(tpm, tpa)
    ft_pct = _safe_div(ftm, fta)
    three_pt_rate = _safe_div(tpa, fga)

    return {
        "possessions": round(poss, 1) if poss > 0 else None,
        "off_rating": round(off_rating, 1) if off_rating is not None else None,
        "def_rating": round(def_rating, 1) if def_rating is not None else None,
        "net_rating": round(net_rating, 1) if net_rating is not None else None,
        "pace": round(pace, 1) if pace is not None else None,
        "off_efg_pct": round(off_efg_pct, 4) if off_efg_pct is not None else None,
        "off_tov_pct": round(off_tov_pct, 4) if off_tov_pct is not None else None,
        "off_orb_pct": round(off_orb_pct, 4) if off_orb_pct is not None else None,
        "off_ft_rate": round(off_ft_rate, 4) if off_ft_rate is not None else None,
        "def_efg_pct": round(def_efg_pct, 4) if def_efg_pct is not None else None,
        "def_tov_pct": round(def_tov_pct, 4) if def_tov_pct is not None else None,
        "def_orb_pct": round(def_orb_pct, 4) if def_orb_pct is not None else None,
        "def_ft_rate": round(def_ft_rate, 4) if def_ft_rate is not None else None,
        "fg_pct": round(fg_pct, 4) if fg_pct is not None else None,
        "three_pt_pct": round(three_pt_pct, 4) if three_pt_pct is not None else None,
        "ft_pct": round(ft_pct, 4) if ft_pct is not None else None,
        "three_pt_rate": round(three_pt_rate, 4) if three_pt_rate is not None else None,
    }


def _compute_single_player_stats(
    player_box: dict,
    team_possessions: float,
    team_minutes: float,
) -> dict:
    """Compute advanced stats for a single player from boxscore data.

    Args:
        player_box: Player boxscore stats JSONB dict.
        team_possessions: Team total possessions for the game.
        team_minutes: Total team minutes (typically 200 for regulation).

    Returns:
        Dict with computed player advanced stats.
    """
    # Extract raw stats
    minutes = _extract_float_stat(player_box, "minutes", 0.0)
    pts = _extract_stat(player_box, "points")
    fgm = _extract_stat(player_box, "fieldGoalsMade")
    fga = _extract_stat(player_box, "fieldGoalsAttempted")
    tpm = _extract_stat(player_box, "threePointsMade")
    ftm = _extract_stat(player_box, "freeThrowsMade")
    fta = _extract_stat(player_box, "freeThrowsAttempted")
    orb = _extract_stat(player_box, "offensiveRebounds")
    drb = _extract_stat(player_box, "defensiveRebounds")
    ast = _extract_stat(player_box, "assists")
    stl = _extract_stat(player_box, "steals")
    blk = _extract_stat(player_box, "blocks")
    tov = _extract_stat(player_box, "turnovers")
    pf = _extract_stat(player_box, "personalFouls")

    total_reb = orb + drb

    # True shooting percentage: PTS / (2 * (FGA + 0.44 * FTA))
    # Use 0.44 even for college per convention
    ts_denom = 2 * (fga + 0.44 * fta)
    ts_pct = _safe_div(pts, ts_denom) if ts_denom > 0 else None

    # Effective FG%: (FGM + 0.5 * 3PM) / FGA
    efg_pct = _safe_div(fgm + 0.5 * tpm, fga)

    # Usage rate: (FGA + 0.475 * FTA + TOV) * (team_min / 5) / (min * team_poss)
    usg_pct = None
    if minutes > 0 and team_possessions > 0 and team_minutes > 0:
        player_usage_events = fga + FTA_COEFF * fta + tov
        usg_pct = (player_usage_events * (team_minutes / 5)) / (minutes * team_possessions)
        usg_pct = round(usg_pct, 4)

    # Offensive rating (simplified per-player): approximate from team off_rating
    # For player-level, we use the same team possessions as the basis
    off_rating = None
    if minutes > 0 and team_possessions > 0:
        # Rough player off rating based on points produced per possession share
        player_poss_share = (fga + FTA_COEFF * fta + tov)
        if player_poss_share > 0:
            off_rating = round((pts / player_poss_share) * 100, 1)

    # Game Score: PTS + 0.4*FG - 0.7*FGA - 0.4*(FTA-FT) + 0.7*ORB + 0.3*DRB
    #             + STL + 0.7*AST + 0.7*BLK - 0.4*PF - TOV
    game_score = (
        pts
        + 0.4 * fgm
        - 0.7 * fga
        - 0.4 * (fta - ftm)
        + 0.7 * orb
        + 0.3 * drb
        + stl
        + 0.7 * ast
        + 0.7 * blk
        - 0.4 * pf
        - tov
    )

    return {
        "minutes": round(minutes, 1) if minutes > 0 else None,
        "off_rating": off_rating,
        "usg_pct": usg_pct,
        "ts_pct": round(ts_pct, 4) if ts_pct is not None else None,
        "efg_pct": round(efg_pct, 4) if efg_pct is not None else None,
        "game_score": round(game_score, 1),
        "points": pts,
        "rebounds": total_reb,
        "assists": ast,
        "steals": stl,
        "blocks": blk,
        "turnovers": tov,
    }


class NCAABAdvancedStatsFetcher:
    """Computes four-factor advanced stats from CBB API boxscore data.

    Unlike MLB/NHL fetchers, this makes ZERO external API calls.
    All metrics are derived from existing boxscore data in the database.
    """

    def compute_team_advanced_stats(
        self,
        home_box: dict,
        away_box: dict,
    ) -> dict[str, dict]:
        """Compute four factors + efficiency for both teams.

        Args:
            home_box: Home team boxscore stats JSONB dict.
            away_box: Away team boxscore stats JSONB dict.

        Returns:
            {"home": {...}, "away": {...}} with all computed advanced stats.
        """
        home_stats = _compute_team_four_factors(home_box, away_box)
        away_stats = _compute_team_four_factors(away_box, home_box)

        logger.info(
            "ncaab_advanced_team_stats_computed",
            home_poss=home_stats.get("possessions"),
            away_poss=away_stats.get("possessions"),
            home_pace=home_stats.get("pace"),
        )

        return {"home": home_stats, "away": away_stats}

    def compute_player_advanced_stats(
        self,
        player_boxes: list[dict],
        team_possessions: float,
        team_minutes: float,
    ) -> list[dict]:
        """Compute per-player advanced stats from boxscore data.

        Args:
            player_boxes: List of player boxscore dicts with 'stats',
                'player_external_ref', 'player_name' keys.
            team_possessions: Team's total possessions for the game.
            team_minutes: Total team minutes (typically 200).

        Returns:
            List of dicts with computed player advanced stats.
        """
        results = []
        for pb in player_boxes:
            stats = pb.get("stats", {})
            computed = _compute_single_player_stats(stats, team_possessions, team_minutes)
            computed["player_external_ref"] = pb.get("player_external_ref", "")
            computed["player_name"] = pb.get("player_name", "")
            results.append(computed)

        logger.info(
            "ncaab_advanced_player_stats_computed",
            player_count=len(results),
            team_possessions=round(team_possessions, 1) if team_possessions else 0,
        )

        return results
