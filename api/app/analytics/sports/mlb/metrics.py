"""MLB-specific metric calculations.

Computes derived batting, pitching, and fielding metrics from raw
box score and Statcast data. Intended to work with data already
ingested into ``mlb_game_advanced_stats`` and ``mlb_player_advanced_stats``.

Future metrics:
- Swing rate, contact rate, zone awareness
- Expected slugging (xSLG) from exit velocity + launch angle
- Barrel rate, hard-hit rate
- Pitcher quality scores (K-BB%, FIP components)
- Base running efficiency
"""

from __future__ import annotations

from typing import Any

from app.analytics.core.types import PlayerProfile, TeamProfile


class MLBMetrics:
    """Compute MLB-specific analytical metrics."""

    def build_player_profile(self, stats: dict[str, Any]) -> PlayerProfile:
        """Build an MLB player analytical profile from raw stats.

        Args:
            stats: Raw stat dictionary from boxscore/Statcast ingestion.

        Returns:
            PlayerProfile with computed MLB metrics.
        """
        return PlayerProfile(
            player_id=str(stats.get("player_id", "")),
            sport="mlb",
        )

    def build_team_profile(self, stats: dict[str, Any]) -> TeamProfile:
        """Build an MLB team analytical profile from aggregated stats.

        Args:
            stats: Aggregated team stat dictionary.

        Returns:
            TeamProfile with computed MLB team metrics.
        """
        return TeamProfile(
            team_id=str(stats.get("team_id", "")),
            sport="mlb",
        )
