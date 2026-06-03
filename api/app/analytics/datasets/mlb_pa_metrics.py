"""Metric extraction helpers for MLB PA datasets."""

from __future__ import annotations

from typing import Any


def _boxscore_batting_metrics(raw: dict) -> dict[str, float]:
    """Extract standard batting metrics from SportsPlayerBoxscore raw_stats.

    These supplement the Statcast-derived metrics from MLBPlayerAdvancedStats,
    giving the model access to traditional slash-line stats (AVG/OBP/SLG)
    and counting stats (H, HR, BB, K) that Statcast alone doesn't capture.
    """
    ab = float(raw.get("atBats", 0) or 0)
    h = float(raw.get("hits", 0) or 0)
    hr = float(raw.get("homeRuns", 0) or 0)
    bb = float(raw.get("baseOnBalls", 0) or 0)
    so = float(raw.get("strikeOuts", 0) or 0)
    doubles = float(raw.get("doubles", 0) or 0)
    triples = float(raw.get("triples", 0) or 0)
    rbi = float(raw.get("rbi", 0) or 0)

    def _parse_float(val: Any, default: float) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    return {
        "box_at_bats": ab,
        "box_hits": h,
        "box_home_runs": hr,
        "box_walks": bb,
        "box_strikeouts": so,
        "box_doubles": doubles,
        "box_triples": triples,
        "box_rbi": rbi,
        "box_avg": _parse_float(raw.get("avg"), 0.250),
        "box_obp": _parse_float(raw.get("obp"), 0.320),
        "box_slg": _parse_float(raw.get("slg"), 0.400),
        "box_ops": _parse_float(raw.get("ops"), 0.720),
        # Per-AB rates for single-game context
        "box_k_rate": (so / ab) if ab > 0 else 0.22,
        "box_bb_rate": (bb / (ab + bb)) if (ab + bb) > 0 else 0.08,
        "box_hr_rate": (hr / ab) if ab > 0 else 0.03,
        "box_iso": ((doubles + 2 * triples + 3 * hr) / ab) if ab > 0 else 0.150,
    }


def _pitcher_stats_to_metrics(stats: Any) -> dict[str, float]:
    """Convert MLBPitcherGameStats to a metrics dict for rolling profiles."""
    bf = stats.batters_faced or 0
    ip = stats.innings_pitched or 0.0

    total_swings = (stats.zone_swings or 0) + (stats.outside_swings or 0)
    total_contact = (stats.zone_contact or 0) + (stats.outside_contact or 0)
    bip = stats.balls_in_play or 0
    er = stats.earned_runs or 0
    h = stats.hits or 0
    bb = stats.walks or 0
    hr = stats.home_runs_allowed or 0

    return {
        "innings_pitched": float(ip),
        "batters_faced": float(bf),
        "strikeouts": float(stats.strikeouts or 0),
        "walks": float(bb),
        "home_runs_allowed": float(hr),
        "hits": float(h),
        "earned_runs": float(er),
        "pitches_thrown": float(stats.pitches_thrown or 0),
        # Traditional derived rates (from stored IP, H, ER, BB, HR)
        "era": (er * 9.0 / ip) if ip > 0 else 4.50,
        "whip": ((bb + h) / ip) if ip > 0 else 1.30,
        "h_per_9": (h * 9.0 / ip) if ip > 0 else 9.0,
        "hr_per_9": (hr * 9.0 / ip) if ip > 0 else 1.2,
        "k_per_9": ((stats.strikeouts or 0) * 9.0 / ip) if ip > 0 else 8.5,
        "bb_per_9": (bb * 9.0 / ip) if ip > 0 else 3.2,
        # Statcast rates
        "k_rate": (stats.strikeouts / bf) if bf > 0 else 0.22,
        "bb_rate": (bb / bf) if bf > 0 else 0.08,
        "hr_rate": (hr / bf) if bf > 0 else 0.03,
        "whiff_rate": (
            1.0 - (total_contact / total_swings) if total_swings > 0 else 0.23
        ),
        "z_contact_pct": (
            (stats.zone_contact / stats.zone_swings)
            if (stats.zone_swings or 0) > 0 else 0.84
        ),
        "chase_rate": (
            (stats.outside_swings / stats.outside_pitches)
            if (stats.outside_pitches or 0) > 0 else 0.32
        ),
        "avg_exit_velo_against": (
            (stats.total_exit_velo_against / bip) if bip > 0 else 88.0
        ),
        "hard_hit_pct_against": (
            (stats.hard_hit_against / bip) if bip > 0 else 0.35
        ),
        "barrel_pct_against": (
            (stats.barrel_against / bip) if bip > 0 else 0.07
        ),
        # Contact/power suppression for matchup compatibility
        "contact_suppression": max(-0.15, min(0.30,
            1.0 - (h / bf) - 0.30 if bf > 0 else 0.0
        )),
        "power_suppression": max(-0.30, min(0.50,
            1.0 - ((hr / bf) / 0.03) if bf > 0 else 0.0
        )),
        # Aliases for matchup.py compatibility (same values as k_rate/bb_rate)
        "strikeout_rate": (stats.strikeouts / bf) if bf > 0 else 0.22,
        "walk_rate": (bb / bf) if bf > 0 else 0.08,
    }
