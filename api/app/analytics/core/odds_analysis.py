"""Odds analysis: convert and compare model probabilities vs sportsbook odds.

Provides American odds conversion and edge calculation utilities.
Stateless and lightweight — no database access.

Usage::

    odds = OddsAnalysis()
    prob = odds.american_to_implied_probability(-200)  # 0.6667
    edge = odds.compare_moneyline(0.65, -150)
"""

from __future__ import annotations


class OddsAnalysis:
    """Convert odds formats and compare model vs sportsbook probabilities."""

    def american_to_implied_probability(self, odds: int) -> float:
        """Convert American odds to implied probability.

        Args:
            odds: American odds (e.g., -200, +150).

        Returns:
            Implied probability (0-1). Returns 0.0 for invalid input.
        """
        if odds == 0:
            return 0.0
        if odds < 0:
            return round(abs(odds) / (abs(odds) + 100), 4)
        return round(100 / (odds + 100), 4)

    def compare_moneyline(
        self,
        model_probability: float,
        american_odds: int,
    ) -> dict[str, float]:
        """Compare model win probability to sportsbook moneyline.

        Args:
            model_probability: Model's estimated probability (0-1).
            american_odds: Sportsbook American odds.

        Returns:
            Dict with model probability, implied probability, and edge.
        """
        implied = self.american_to_implied_probability(american_odds)
        return {
            "model_probability": round(model_probability, 4),
            "sportsbook_implied_probability": implied,
            "edge": round(model_probability - implied, 4),
        }

    def compare_spread(
        self,
        model_cover_probability: float,
        american_odds: int,
    ) -> dict[str, float]:
        """Compare model spread cover probability to sportsbook odds.

        Args:
            model_cover_probability: Model's cover probability (0-1).
            american_odds: Sportsbook odds for the spread.

        Returns:
            Dict with model probability, implied probability, and edge.
        """
        implied = self.american_to_implied_probability(american_odds)
        return {
            "model_probability": round(model_cover_probability, 4),
            "sportsbook_implied_probability": implied,
            "edge": round(model_cover_probability - implied, 4),
        }

    def compare_total(
        self,
        model_over_probability: float,
        american_odds: int,
    ) -> dict[str, float]:
        """Compare model over probability to sportsbook total odds.

        Args:
            model_over_probability: Model's over probability (0-1).
            american_odds: Sportsbook odds for the over.

        Returns:
            Dict with model probability, implied probability, and edge.
        """
        implied = self.american_to_implied_probability(american_odds)
        return {
            "model_probability": round(model_over_probability, 4),
            "sportsbook_implied_probability": implied,
            "edge": round(model_over_probability - implied, 4),
        }
