"""NFL advanced stats fetcher using nflverse via nflreadpy.

Fetches pre-computed EPA/WPA/CPOE from nflverse Parquet files and
aggregates into team-level and player-level stats for a single game.
"""

from __future__ import annotations

from ..config import settings
from ..logging import logger
from ..utils.cache import APICache
from ..utils.math import safe_div as _safe_div
from ..utils.math import safe_float as _safe_float


class NFLAdvancedStatsFetcher:
    """Fetches pre-computed EPA/WPA/CPOE from nflverse via nflreadpy."""

    def __init__(self) -> None:
        self._cache = APICache(
            cache_dir=settings.scraper_config.html_cache_dir,
            api_name="nfl_advanced",
        )

    def fetch_game_plays(
        self,
        espn_game_id: int,
        season: int,
        *,
        home_abbr: str | None = None,
        away_abbr: str | None = None,
        game_date: str | None = None,
    ) -> list[dict]:
        """Load season PBP from nflverse, filter to this game's plays.

        Matching strategy: nflverse has no ESPN event ID field. We match
        by game_date + home_team + away_team from the play data. Each
        play has home_team, away_team, and game_date fields.

        Falls back to old_game_id matching if team info is not provided.

        Returns list of play dicts or empty list on failure.
        """
        all_plays = self._load_season_plays(season)
        if not all_plays:
            return []

        # Primary match: date + teams (most reliable)
        if home_abbr and away_abbr and game_date:
            matched = [
                p for p in all_plays
                if (p.get("home_team") == home_abbr
                    and p.get("away_team") == away_abbr
                    and str(p.get("game_date")) == game_date)
            ]
            if matched:
                return matched
            # Try swapped teams (some nflverse data may swap home/away)
            matched = [
                p for p in all_plays
                if (p.get("away_team") == home_abbr
                    and p.get("home_team") == away_abbr
                    and str(p.get("game_date")) == game_date)
            ]
            if matched:
                return matched

        # Fallback: old_game_id (GSIS format, not ESPN — unlikely to match)
        return [
            p for p in all_plays
            if str(p.get("old_game_id")) == str(espn_game_id)
        ]

    def _load_season_plays(self, season: int) -> list[dict]:
        """Load and cache all plays for a season from nflverse."""
        cache_key = f"nflverse_pbp_{season}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            import nflreadpy as nfl
        except ImportError:
            logger.warning("nflreadpy_not_installed")
            return []

        try:
            pbp = nfl.load_pbp([season])
            all_plays = pbp.to_dicts()
            if all_plays:
                self._cache.put(cache_key, all_plays)
            return all_plays
        except Exception as exc:
            logger.warning("nflverse_fetch_error", error=str(exc))
            return []

    def aggregate_team_stats(self, plays: list[dict]) -> dict[str, dict]:
        """Aggregate plays into home/away team EPA/WPA stats.

        Groups by posteam (team with possession) and computes sums/averages
        for EPA, WPA, CPOE, success rates, and explosive play rates.

        Returns {"home": {...}, "away": {...}} keyed by home_team/away_team.
        """
        if not plays:
            return {"home": {}, "away": {}}

        # Determine home/away team from the first play
        home_team = None
        away_team = None
        for p in plays:
            ht = p.get("home_team")
            at = p.get("away_team")
            if ht and at:
                home_team = ht
                away_team = at
                break

        if not home_team or not away_team:
            return {"home": {}, "away": {}}

        # Filter to real plays with EPA (exclude timeouts, penalties without plays)
        real_plays = [p for p in plays if _safe_float(p.get("epa")) is not None]

        result = {}
        for side, team_abbr in [("home", home_team), ("away", away_team)]:
            team_plays = [p for p in real_plays if p.get("posteam") == team_abbr]

            if not team_plays:
                result[side] = {}
                continue

            pass_plays = [
                p for p in team_plays
                if p.get("pass_attempt") == 1 or p.get("pass_attempt") == 1.0
            ]
            rush_plays = [
                p for p in team_plays
                if p.get("rush_attempt") == 1 or p.get("rush_attempt") == 1.0
            ]

            total_epa = sum(_safe_float(p.get("epa")) or 0.0 for p in team_plays)
            pass_epa = sum(_safe_float(p.get("epa")) or 0.0 for p in pass_plays)
            rush_epa = sum(_safe_float(p.get("epa")) or 0.0 for p in rush_plays)
            total_wpa = sum(_safe_float(p.get("wpa")) or 0.0 for p in team_plays)

            # Success: plays where epa > 0
            successes = sum(1 for p in team_plays if (_safe_float(p.get("epa")) or 0) > 0)
            pass_successes = sum(1 for p in pass_plays if (_safe_float(p.get("epa")) or 0) > 0)
            rush_successes = sum(1 for p in rush_plays if (_safe_float(p.get("epa")) or 0) > 0)

            # Explosive plays: 20+ yard pass, 12+ yard rush
            explosive_count = 0
            for p in pass_plays:
                yds = _safe_float(p.get("yards_gained"))
                if yds is not None and yds >= 20:
                    explosive_count += 1
            for p in rush_plays:
                yds = _safe_float(p.get("yards_gained"))
                if yds is not None and yds >= 12:
                    explosive_count += 1

            # CPOE — only on pass attempts with cpoe
            cpoe_vals = [
                _safe_float(p.get("cpoe"))
                for p in pass_plays
                if _safe_float(p.get("cpoe")) is not None
            ]

            # Air yards
            air_yards_vals = [
                _safe_float(p.get("air_yards"))
                for p in pass_plays
                if _safe_float(p.get("air_yards")) is not None
            ]

            # YAC
            yac_vals = [
                _safe_float(p.get("yards_after_catch"))
                for p in pass_plays
                if _safe_float(p.get("yards_after_catch")) is not None
            ]

            total_play_count = len(team_plays)
            pass_play_count = len(pass_plays)
            rush_play_count = len(rush_plays)

            result[side] = {
                "total_epa": round(total_epa, 3),
                "pass_epa": round(pass_epa, 3),
                "rush_epa": round(rush_epa, 3),
                "epa_per_play": round(total_epa / total_play_count, 4) if total_play_count else None,
                "total_wpa": round(total_wpa, 4),
                "success_rate": _safe_div(successes, total_play_count),
                "pass_success_rate": _safe_div(pass_successes, pass_play_count),
                "rush_success_rate": _safe_div(rush_successes, rush_play_count),
                "explosive_play_rate": _safe_div(
                    explosive_count, pass_play_count + rush_play_count
                ),
                "avg_cpoe": (
                    round(sum(cpoe_vals) / len(cpoe_vals), 3)
                    if cpoe_vals else None
                ),
                "avg_air_yards": (
                    round(sum(air_yards_vals) / len(air_yards_vals), 2)
                    if air_yards_vals else None
                ),
                "avg_yac": (
                    round(sum(yac_vals) / len(yac_vals), 2)
                    if yac_vals else None
                ),
                "total_plays": total_play_count,
                "pass_plays": pass_play_count,
                "rush_plays": rush_play_count,
            }

        return result

    def aggregate_player_stats(self, plays: list[dict]) -> list[dict]:
        """Aggregate per-player EPA stats (passers, rushers, receivers).

        Each player can appear in multiple roles (e.g., a QB who also rushes).
        Returns one dict per (player_id, role) combination.
        """
        if not plays:
            return []

        # Determine home/away mapping
        home_team = None
        away_team = None
        for p in plays:
            ht = p.get("home_team")
            at = p.get("away_team")
            if ht and at:
                home_team = ht
                away_team = at
                break

        if not home_team or not away_team:
            return []

        # Filter to real plays with EPA
        real_plays = [p for p in plays if _safe_float(p.get("epa")) is not None]

        # Accumulate stats per (player_id, role)
        # Key: (player_id, role) -> accumulated stats dict
        accum: dict[tuple[str, str], dict] = {}

        role_configs = [
            ("passer", "passer_player_id", "passer_player_name"),
            ("rusher", "rusher_player_id", "rusher_player_name"),
            ("receiver", "receiver_player_id", "receiver_player_name"),
        ]

        for play in real_plays:
            epa = _safe_float(play.get("epa")) or 0.0
            wpa = _safe_float(play.get("wpa")) or 0.0
            success = 1 if epa > 0 else 0
            posteam = play.get("posteam")

            for role, id_col, name_col in role_configs:
                player_id = play.get(id_col)
                player_name = play.get(name_col)
                if not player_id or player_id is None:
                    continue
                player_id_str = str(player_id)

                key = (player_id_str, role)
                if key not in accum:
                    accum[key] = {
                        "player_external_ref": player_id_str,
                        "player_name": player_name or "Unknown",
                        "player_role": role,
                        "posteam": posteam,
                        "total_epa": 0.0,
                        "total_wpa": 0.0,
                        "successes": 0,
                        "plays": 0,
                        "pass_epa": 0.0,
                        "rush_epa": 0.0,
                        "receiving_epa": 0.0,
                        "cpoe_sum": 0.0,
                        "cpoe_count": 0,
                        "air_epa_sum": 0.0,
                        "yac_epa_sum": 0.0,
                        "air_yards_sum": 0.0,
                        "air_yards_count": 0,
                    }

                a = accum[key]
                a["total_epa"] += epa
                a["total_wpa"] += wpa
                a["successes"] += success
                a["plays"] += 1

                if role == "passer":
                    a["pass_epa"] += epa
                    cpoe_val = _safe_float(play.get("cpoe"))
                    if cpoe_val is not None:
                        a["cpoe_sum"] += cpoe_val
                        a["cpoe_count"] += 1
                    air_epa_val = _safe_float(play.get("air_epa"))
                    if air_epa_val is not None:
                        a["air_epa_sum"] += air_epa_val
                    yac_epa_val = _safe_float(play.get("yac_epa"))
                    if yac_epa_val is not None:
                        a["yac_epa_sum"] += yac_epa_val
                    air_yards_val = _safe_float(play.get("air_yards"))
                    if air_yards_val is not None:
                        a["air_yards_sum"] += air_yards_val
                        a["air_yards_count"] += 1
                elif role == "rusher":
                    a["rush_epa"] += epa
                elif role == "receiver":
                    a["receiving_epa"] += epa

        # Convert accumulators to output dicts
        results = []
        for (_pid, _role), a in accum.items():
            posteam = a["posteam"]
            is_home = posteam == home_team

            player_stat = {
                "player_external_ref": a["player_external_ref"],
                "player_name": a["player_name"],
                "player_role": a["player_role"],
                "is_home": is_home,
                "total_epa": round(a["total_epa"], 3),
                "epa_per_play": round(a["total_epa"] / a["plays"], 4) if a["plays"] else None,
                "pass_epa": round(a["pass_epa"], 3) if a["player_role"] == "passer" else None,
                "rush_epa": round(a["rush_epa"], 3) if a["player_role"] == "rusher" else None,
                "receiving_epa": (
                    round(a["receiving_epa"], 3) if a["player_role"] == "receiver" else None
                ),
                "cpoe": (
                    round(a["cpoe_sum"] / a["cpoe_count"], 3)
                    if a["cpoe_count"] > 0 else None
                ),
                "air_epa": round(a["air_epa_sum"], 3) if a["player_role"] == "passer" else None,
                "yac_epa": round(a["yac_epa_sum"], 3) if a["player_role"] == "passer" else None,
                "air_yards": (
                    round(a["air_yards_sum"], 1)
                    if a["air_yards_count"] > 0 and a["player_role"] == "passer"
                    else None
                ),
                "total_wpa": round(a["total_wpa"], 4),
                "success_rate": _safe_div(a["successes"], a["plays"]),
                "plays": a["plays"],
            }
            results.append(player_stat)

        return results
