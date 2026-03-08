"""Simulation analysis: converts raw simulation outputs into structured summaries.

Provides win probabilities, score distributions, spread/total analysis,
and optional sportsbook comparison. Sport-agnostic with routing to
sport-specific modules when needed.

Usage::

    analysis = SimulationAnalysis("mlb")
    summary = analysis.summarize_results(sim_results)
    totals = analysis.summarize_totals(sim_results, total_line=8.5)
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


class SimulationAnalysis:
    """Analyze Monte Carlo simulation outputs."""

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()

    def summarize_results(
        self,
        simulation_results: list[dict[str, Any]],
        sportsbook: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Top-level summary of simulation outputs.

        Args:
            simulation_results: List of game result dicts from SimulationRunner.
            sportsbook: Optional sportsbook lines for comparison.

        Returns:
            Dict with win probabilities, average scores, totals,
            most common scores, and optional odds comparison.
        """
        if not simulation_results:
            return _empty_summary()

        n = len(simulation_results)
        home_wins = sum(1 for r in simulation_results if r.get("winner") == "home")
        home_scores = [r.get("home_score", 0) for r in simulation_results]
        away_scores = [r.get("away_score", 0) for r in simulation_results]
        totals = [h + a for h, a in zip(home_scores, away_scores)]

        home_wp = round(home_wins / n, 4)
        away_wp = round((n - home_wins) / n, 4)
        avg_home = round(sum(home_scores) / n, 2)
        avg_away = round(sum(away_scores) / n, 2)
        avg_total = round(sum(totals) / n, 2)
        median_total = round(_median(totals), 2)

        # Most common scores
        score_counts: Counter[str] = Counter()
        for r in simulation_results:
            key = f"{r.get('home_score', 0)}-{r.get('away_score', 0)}"
            score_counts[key] += 1

        most_common = [
            {"score": score, "probability": round(count / n, 4)}
            for score, count in score_counts.most_common(10)
        ]

        summary: dict[str, Any] = {
            "home_win_probability": home_wp,
            "away_win_probability": away_wp,
            "average_home_score": avg_home,
            "average_away_score": avg_away,
            "average_total": avg_total,
            "median_total": median_total,
            "most_common_scores": most_common,
            "iterations": n,
        }

        # Sportsbook comparison if provided
        if sportsbook:
            from .odds_analysis import OddsAnalysis
            odds = OddsAnalysis()
            comparison: dict[str, Any] = {}

            ml = sportsbook.get("moneyline")
            if ml:
                comparison["moneyline_comparison"] = {
                    "home": odds.compare_moneyline(home_wp, ml.get("home", 0)),
                    "away": odds.compare_moneyline(away_wp, ml.get("away", 0)),
                }

            spread = sportsbook.get("spread")
            if spread:
                spread_result = self.summarize_spreads(
                    simulation_results, spread.get("home_line", 0),
                )
                comparison["spread_comparison"] = odds.compare_spread(
                    spread_result["home_cover_probability"],
                    spread.get("home_odds", -110),
                )

            total = sportsbook.get("total")
            if total:
                total_result = self.summarize_totals(
                    simulation_results, total.get("line", 0),
                )
                comparison["total_comparison"] = odds.compare_total(
                    total_result["over_probability"],
                    total.get("over_odds", -110),
                )

            summary["sportsbook_comparison"] = comparison

        return summary

    def summarize_distribution(
        self,
        simulation_results: list[dict[str, Any]],
        top_n: int = 20,
    ) -> dict[str, Any]:
        """Score frequency distribution.

        Returns:
            Dict with ``score_distribution`` (normalized) and
            ``top_scores`` (sorted list).
        """
        if not simulation_results:
            return {"score_distribution": {}, "top_scores": []}

        n = len(simulation_results)
        counts: Counter[str] = Counter()
        for r in simulation_results:
            key = f"{r.get('home_score', 0)}-{r.get('away_score', 0)}"
            counts[key] += 1

        distribution = {
            score: round(count / n, 4)
            for score, count in counts.most_common()
        }
        top_scores = [
            {"score": score, "probability": round(count / n, 4)}
            for score, count in counts.most_common(top_n)
        ]

        return {
            "score_distribution": distribution,
            "top_scores": top_scores,
        }

    def summarize_team_totals(
        self,
        simulation_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Per-team score distributions.

        Returns:
            Dict with home/away score distributions, averages, and medians.
        """
        if not simulation_results:
            return _empty_team_totals()

        n = len(simulation_results)
        home_scores = [r.get("home_score", 0) for r in simulation_results]
        away_scores = [r.get("away_score", 0) for r in simulation_results]

        home_dist = _score_distribution(home_scores, n)
        away_dist = _score_distribution(away_scores, n)

        return {
            "home_score_distribution": home_dist,
            "away_score_distribution": away_dist,
            "average_home_score": round(sum(home_scores) / n, 2),
            "average_away_score": round(sum(away_scores) / n, 2),
            "median_home_score": _median(home_scores),
            "median_away_score": _median(away_scores),
        }

    def summarize_spreads(
        self,
        simulation_results: list[dict[str, Any]],
        spread_line: float,
    ) -> dict[str, Any]:
        """Spread cover probabilities.

        Args:
            simulation_results: List of game result dicts.
            spread_line: Home team spread (e.g., -1.5 means home favored).

        Returns:
            Dict with home_cover, away_cover, and push probabilities.
        """
        if not simulation_results:
            return {"spread_line": spread_line, "home_cover_probability": 0.0,
                    "away_cover_probability": 0.0, "push_probability": 0.0}

        n = len(simulation_results)
        home_cover = 0
        away_cover = 0
        push = 0

        for r in simulation_results:
            margin = r.get("home_score", 0) - r.get("away_score", 0)
            adjusted = margin + spread_line
            if adjusted > 0:
                home_cover += 1
            elif adjusted < 0:
                away_cover += 1
            else:
                push += 1

        return {
            "spread_line": spread_line,
            "home_cover_probability": round(home_cover / n, 4),
            "away_cover_probability": round(away_cover / n, 4),
            "push_probability": round(push / n, 4),
        }

    def summarize_totals(
        self,
        simulation_results: list[dict[str, Any]],
        total_line: float,
    ) -> dict[str, Any]:
        """Over/under probabilities for a given total line.

        Args:
            simulation_results: List of game result dicts.
            total_line: Total line (e.g., 8.5).

        Returns:
            Dict with over, under, and push probabilities.
        """
        if not simulation_results:
            return {"total_line": total_line, "over_probability": 0.0,
                    "under_probability": 0.0, "push_probability": 0.0}

        n = len(simulation_results)
        over = 0
        under = 0
        push = 0

        for r in simulation_results:
            total = r.get("home_score", 0) + r.get("away_score", 0)
            if total > total_line:
                over += 1
            elif total < total_line:
                under += 1
            else:
                push += 1

        return {
            "total_line": total_line,
            "over_probability": round(over / n, 4),
            "under_probability": round(under / n, 4),
            "push_probability": round(push / n, 4),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _median(values: list[int | float]) -> float:
    """Compute median of a list."""
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return float(s[mid])


def _score_distribution(scores: list[int], n: int) -> dict[str, float]:
    """Build a normalized distribution of integer scores."""
    counts: Counter[int] = Counter(scores)
    return {
        str(score): round(count / n, 4)
        for score, count in sorted(counts.items())
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "home_win_probability": 0.0,
        "away_win_probability": 0.0,
        "average_home_score": 0.0,
        "average_away_score": 0.0,
        "average_total": 0.0,
        "median_total": 0.0,
        "most_common_scores": [],
        "iterations": 0,
    }


def _empty_team_totals() -> dict[str, Any]:
    return {
        "home_score_distribution": {},
        "away_score_distribution": {},
        "average_home_score": 0.0,
        "average_away_score": 0.0,
        "median_home_score": 0.0,
        "median_away_score": 0.0,
    }
