"""NBA advanced stats computation (derived from boxscore data).

Computes efficiency ratings, four factors, and shooting metrics from
existing team and player boxscore data already in the database.
No external API calls needed — all metrics are derived from the NBA CDN
boxscore data stored in sports_team_boxscores and sports_player_boxscores.

NBA uses 0.44 FTA coefficient (vs 0.475 for college) and 48-minute games.

TODO: Investigate residential proxy or alternative API source for
stats.nba.com tracking data (speed, distance, touches, contested shots,
pull-up/catch-shoot splits, hustle stats). These require NBA's optical
tracking system and cannot be derived from boxscores. The stats.nba.com
API blocks cloud/datacenter IPs.
"""

from __future__ import annotations

from ..utils.math import safe_div as _safe_div

# NBA-specific constants
FTA_COEFF = 0.44  # NBA possession coefficient (0.475 for college)
REGULATION_MINUTES = 48  # 48-minute games (40 for college)
STANDARD_TEAM_MINUTES = 240  # 5 players * 48 minutes


def _extract_stat(box: dict, key: str, default: int = 0) -> int:
    """Extract an integer stat from boxscore JSONB."""
    val = box.get(key, default)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _extract_float(box: dict, key: str, default: float = 0.0) -> float:
    """Extract a float stat from boxscore JSONB."""
    val = box.get(key, default)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _compute_possessions(fga: int, orb: int, tov: int, fta: int) -> float:
    """Compute possessions: FGA - ORB + TOV + 0.44 * FTA."""
    return fga - orb + tov + FTA_COEFF * fta


class NBAAdvancedStatsFetcher:
    """Computes NBA advanced stats from existing boxscore data.

    No external API calls — reads from sports_team_boxscores and
    sports_player_boxscores JSONB columns.
    """

    def compute_team_advanced_stats(
        self, home_box: dict, away_box: dict, home_points: int, away_points: int,
    ) -> dict[str, dict]:
        """Compute advanced stats for both teams.

        Args:
            home_box: Home team boxscore stats JSONB dict.
            away_box: Away team boxscore stats JSONB dict.
            home_points: Home team final score.
            away_points: Away team final score.

        Returns:
            {"home": {...}, "away": {...}} with computed advanced stats.
        """
        home_stats = self._compute_single_team(home_box, away_box, home_points, away_points)
        away_stats = self._compute_single_team(away_box, home_box, away_points, home_points)
        return {"home": home_stats, "away": away_stats}

    def _compute_single_team(
        self, box: dict, opp_box: dict, pts: int, opp_pts: int,
    ) -> dict:
        """Compute advanced stats for one team."""
        # Extract raw stats — team offense (NBA CDN key names)
        fgm = _extract_stat(box, "fg_made")
        fga = _extract_stat(box, "fg_attempted")
        tpm = _extract_stat(box, "three_made")
        tpa = _extract_stat(box, "three_attempted")
        ftm = _extract_stat(box, "ft_made")
        fta = _extract_stat(box, "ft_attempted")
        orb = _extract_stat(box, "offensive_rebounds")
        drb = _extract_stat(box, "defensive_rebounds")
        tov = _extract_stat(box, "turnovers") or _extract_stat(box, "team_turnovers")
        ast = _extract_stat(box, "assists")

        # Opponent stats (for defensive metrics)
        opp_fga = _extract_stat(opp_box, "fg_attempted")
        opp_tpm = _extract_stat(opp_box, "three_made")
        opp_fta = _extract_stat(opp_box, "ft_attempted")
        opp_orb = _extract_stat(opp_box, "offensive_rebounds")
        opp_drb = _extract_stat(opp_box, "defensive_rebounds")
        opp_tov = _extract_stat(opp_box, "turnovers") or _extract_stat(opp_box, "team_turnovers")

        # Possessions
        poss = _compute_possessions(fga, orb, tov, fta)
        opp_poss = _compute_possessions(opp_fga, opp_orb, opp_tov, opp_fta)

        # Efficiency ratings
        off_rating = _safe_div(pts * 100, poss) if poss > 0 else None
        def_rating = _safe_div(opp_pts * 100, poss) if poss > 0 else None
        net_rating = (off_rating - def_rating) if off_rating and def_rating else None

        # Pace
        avg_poss = (poss + opp_poss) / 2 if (poss + opp_poss) > 0 else 0
        pace = avg_poss * REGULATION_MINUTES / (STANDARD_TEAM_MINUTES / 5) if avg_poss > 0 else None

        # Shooting
        efg_pct = _safe_div(fgm + 0.5 * tpm, fga)
        ts_pct = _safe_div(pts, 2 * (fga + FTA_COEFF * fta)) if (fga + FTA_COEFF * fta) > 0 else None
        fg_pct = _safe_div(fgm, fga)
        fg3_pct = _safe_div(tpm, tpa) if tpa > 0 else None
        ft_pct = _safe_div(ftm, fta) if fta > 0 else None

        # Rebounding
        orb_pct = _safe_div(orb, orb + opp_drb)
        drb_pct = _safe_div(drb, drb + opp_orb)
        reb_pct = _safe_div(orb + drb, orb + drb + opp_orb + opp_drb)

        # Ball movement
        ast_pct = _safe_div(ast, fgm) if fgm > 0 else None
        tov_pct = _safe_div(tov, fga + FTA_COEFF * fta + tov) if (fga + FTA_COEFF * fta + tov) > 0 else None
        ast_tov_ratio = _safe_div(ast, tov) if tov > 0 else None
        ft_rate = _safe_div(fta, fga)

        # Four factors — defense
        def_efg_pct = _safe_div(
            _extract_stat(opp_box, "fg_made") + 0.5 * opp_tpm, opp_fga
        )
        def_tov_pct = (
            _safe_div(opp_tov, opp_fga + FTA_COEFF * opp_fta + opp_tov)
            if (opp_fga + FTA_COEFF * opp_fta + opp_tov) > 0
            else None
        )
        def_orb_pct = _safe_div(opp_orb, opp_orb + drb)
        def_ft_rate = _safe_div(opp_fta, opp_fga)

        # Paint / transition (directly from boxscore)
        paint_points = _extract_stat(box, "points_in_paint") or None
        fastbreak_points = _extract_stat(box, "fast_break_points") or None
        second_chance_points = _extract_stat(box, "second_chance_points") or None
        points_off_turnovers = _extract_stat(box, "points_off_turnovers") or None
        bench_points = _extract_stat(box, "bench_points") or None

        return {
            "off_rating": round(off_rating, 1) if off_rating else None,
            "def_rating": round(def_rating, 1) if def_rating else None,
            "net_rating": round(net_rating, 1) if net_rating else None,
            "pace": round(pace, 1) if pace else None,
            "pie": None,  # PIE requires league averages — skip for derived
            "efg_pct": efg_pct,
            "ts_pct": ts_pct,
            "fg_pct": fg_pct,
            "fg3_pct": fg3_pct,
            "ft_pct": ft_pct,
            "orb_pct": orb_pct,
            "drb_pct": drb_pct,
            "reb_pct": reb_pct,
            "ast_pct": ast_pct,
            "ast_ratio": None,  # Requires play-by-play for true AST ratio
            "ast_tov_ratio": round(ast_tov_ratio, 2) if ast_tov_ratio else None,
            "tov_pct": tov_pct,
            "ft_rate": ft_rate,
            # Four factors — defense
            "def_efg_pct": def_efg_pct,
            "def_tov_pct": def_tov_pct,
            "def_orb_pct": def_orb_pct,
            "def_ft_rate": def_ft_rate,
            # Hustle — not available from boxscore (requires stats.nba.com tracking)
            "contested_shots": None,
            "deflections": None,
            "charges_drawn": None,
            "loose_balls_recovered": None,
            # Paint / transition
            "paint_points": paint_points,
            "fastbreak_points": fastbreak_points,
            "second_chance_points": second_chance_points,
            "points_off_turnovers": points_off_turnovers,
            "bench_points": bench_points,
        }

    def compute_player_advanced_stats(
        self,
        player_boxes: list[dict],
        team_possessions: float,
        team_minutes: float,
    ) -> list[dict]:
        """Compute per-player advanced stats from boxscore data.

        Args:
            player_boxes: List of dicts with player_id, player_name, is_home, stats.
            team_possessions: Team's total possessions for the game.
            team_minutes: Total team minutes (usually 240 for regulation).

        Returns:
            List of dicts with player-level advanced stats.
        """
        results = []
        for pb in player_boxes:
            stats = pb.get("stats", {})
            minutes = _extract_float(stats, "minutes", 0)
            if minutes <= 0:
                continue

            fgm = _extract_stat(stats, "fg_made")
            fga = _extract_stat(stats, "fg_attempted")
            tpm = _extract_stat(stats, "three_made")
            ftm = _extract_stat(stats, "ft_made")
            fta = _extract_stat(stats, "ft_attempted")
            pts = _extract_stat(stats, "points") or (fgm * 2 + tpm + ftm)
            orb = _extract_stat(stats, "offensive_rebounds")
            drb = _extract_stat(stats, "defensive_rebounds")
            ast = _extract_stat(stats, "assists")
            stl = _extract_stat(stats, "steals")
            blk = _extract_stat(stats, "blocks")
            tov = _extract_stat(stats, "turnovers")
            pf = _extract_stat(stats, "personal_fouls")

            # TS% and eFG%
            ts_pct = _safe_div(pts, 2 * (fga + FTA_COEFF * fta)) if (fga + FTA_COEFF * fta) > 0 else None
            efg_pct = _safe_div(fgm + 0.5 * tpm, fga) if fga > 0 else None

            # Usage rate
            usg_pct = None
            if team_possessions > 0 and team_minutes > 0 and minutes > 0:
                usg_numerator = (fga + FTA_COEFF * fta + tov) * (team_minutes / 5)
                usg_denominator = minutes * team_possessions
                usg_pct = _safe_div(usg_numerator, usg_denominator)

            # Game Score (John Hollinger)
            game_score = (
                pts + 0.4 * fgm - 0.7 * fga - 0.4 * (fta - ftm)
                + 0.7 * orb + 0.3 * drb + stl + 0.7 * ast + 0.7 * blk
                - 0.4 * pf - tov
            )

            results.append({
                "player_id": pb.get("player_id"),
                "player_name": pb.get("player_name"),
                "is_home": pb.get("is_home"),
                "minutes": round(minutes, 1),
                "off_rating": None,  # Per-player ratings require on/off court data
                "def_rating": None,
                "net_rating": None,
                "usg_pct": round(usg_pct, 4) if usg_pct else None,
                "pie": None,
                "ts_pct": ts_pct,
                "efg_pct": efg_pct,
                "game_score": round(game_score, 1),
                # Tracking — not available from boxscore
                "speed": None,
                "distance": None,
                "touches": None,
                "time_of_possession": None,
                # Shot context — not available from boxscore
                "contested_2pt_fga": None,
                "contested_2pt_fgm": None,
                "uncontested_2pt_fga": None,
                "uncontested_2pt_fgm": None,
                "contested_3pt_fga": None,
                "contested_3pt_fgm": None,
                "uncontested_3pt_fga": None,
                "uncontested_3pt_fgm": None,
                "pull_up_fga": None,
                "pull_up_fgm": None,
                "catch_shoot_fga": None,
                "catch_shoot_fgm": None,
                # Hustle — not available from boxscore
                "contested_shots": None,
                "deflections": None,
                "charges_drawn": None,
                "loose_balls_recovered": None,
                "screen_assists": None,
            })

        return results
