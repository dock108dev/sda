"""Profile builder: converts aggregated stats into analytics profiles.

Sits between the AggregationEngine (which produces averaged stat dicts)
and the final PlayerProfile/TeamProfile types. Uses the MetricsEngine
to compute derived metrics from the aggregated inputs.

Usage::

    builder = ProfileBuilder("mlb")
    profile = builder.build_player_profile("p123", aggregated_stats)
    # profile.metrics contains derived metrics like contact_rate, power_index
"""

from __future__ import annotations

from typing import Any

from .metrics_engine import MetricsEngine
from .types import PlayerProfile, TeamProfile


class ProfileBuilder:
    """Convert aggregated stat dicts into typed analytics profiles."""

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()
        self._metrics = MetricsEngine(self.sport)

    def build_player_profile(
        self,
        player_id: str,
        aggregated_stats: dict[str, Any],
    ) -> PlayerProfile:
        """Build a PlayerProfile from aggregated historical stats.

        Args:
            player_id: Player identifier.
            aggregated_stats: Output from AggregationEngine.

        Returns:
            PlayerProfile with derived metrics populated.
        """
        metrics = self._metrics.calculate_player_metrics(aggregated_stats)
        return PlayerProfile(
            player_id=player_id,
            sport=self.sport,
            name=str(aggregated_stats.get("name", "")),
            team_id=aggregated_stats.get("team_id"),
            metrics=metrics,
        )

    def build_team_profile(
        self,
        team_id: str,
        aggregated_stats: dict[str, Any],
    ) -> TeamProfile:
        """Build a TeamProfile from aggregated historical stats.

        Args:
            team_id: Team identifier.
            aggregated_stats: Output from AggregationEngine.

        Returns:
            TeamProfile with derived team metrics populated.
        """
        metrics = self._metrics.calculate_team_metrics(aggregated_stats)
        return TeamProfile(
            team_id=team_id,
            sport=self.sport,
            name=str(aggregated_stats.get("name", "")),
            metrics=metrics,
        )
