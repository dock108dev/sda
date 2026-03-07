"""Central aggregation engine for historical stat data.

Transforms raw game-level statistics into aggregated inputs suitable
for the MetricsEngine and ProfileBuilder. Routes aggregation to
sport-specific modules.

Usage::

    engine = AggregationEngine("mlb")
    agg = engine.aggregate_player_history("player123", games)
    # agg is a dict of averaged stat keys ready for MetricsEngine
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Registry mapping sport codes to (module_path, class_name).
_SPORT_AGGREGATION: dict[str, tuple[str, str]] = {
    "mlb": ("app.analytics.sports.mlb.aggregation", "MLBAggregation"),
}


class AggregationEngine:
    """Sport-agnostic aggregation orchestrator.

    Delegates to sport-specific aggregation classes that know how
    to combine raw game stat records into averaged/weighted outputs.
    """

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()
        self._agg_instance: Any | None = None

    def _get_sport_aggregation(self) -> Any:
        """Lazily load and cache the sport-specific aggregation class."""
        if self._agg_instance is not None:
            return self._agg_instance

        entry = _SPORT_AGGREGATION.get(self.sport)
        if entry is None:
            logger.warning("no_aggregation_module", extra={"sport": self.sport})
            return None

        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        self._agg_instance = cls()
        return self._agg_instance

    def aggregate_player_history(
        self,
        player_id: str,
        games: list[dict[str, Any]],
        *,
        recent_n: int | None = None,
        recent_weight: float = 0.7,
        season_weight: float = 0.3,
    ) -> dict[str, Any]:
        """Aggregate historical game stats into player profile inputs.

        Args:
            player_id: Player identifier (included in output).
            games: List of per-game stat dicts for this player.
            recent_n: If set, compute a weighted blend of the last
                ``recent_n`` games vs the full season.
            recent_weight: Weight for the recent window (0-1).
            season_weight: Weight for the full-season average (0-1).

        Returns:
            Dict of aggregated stat keys ready for MetricsEngine,
            including ``player_id``.
        """
        agg = self._get_sport_aggregation()
        if agg is None:
            return {"player_id": player_id}

        result = agg.aggregate_player_games(
            games,
            recent_n=recent_n,
            recent_weight=recent_weight,
            season_weight=season_weight,
        )
        result["player_id"] = player_id
        return result

    def aggregate_team_history(
        self,
        team_id: str,
        games: list[dict[str, Any]],
        *,
        recent_n: int | None = None,
        recent_weight: float = 0.7,
        season_weight: float = 0.3,
    ) -> dict[str, Any]:
        """Aggregate team game stats into team profile inputs.

        Args:
            team_id: Team identifier (included in output).
            games: List of per-game team stat dicts.
            recent_n: If set, blend recent window vs full season.
            recent_weight: Weight for the recent window.
            season_weight: Weight for the full-season average.

        Returns:
            Dict of aggregated stat keys ready for MetricsEngine,
            including ``team_id``.
        """
        agg = self._get_sport_aggregation()
        if agg is None:
            return {"team_id": team_id}

        result = agg.aggregate_team_games(
            games,
            recent_n=recent_n,
            recent_weight=recent_weight,
            season_weight=season_weight,
        )
        result["team_id"] = team_id
        return result

    def build_matchup_dataset(
        self,
        entity_a_id: str,
        entity_b_id: str,
        entity_a_games: list[dict[str, Any]],
        entity_b_games: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Prepare historical data for matchup modeling.

        Aggregates both entities' histories and returns them as a
        structured dataset ready for matchup analysis.

        Args:
            entity_a_id: First entity identifier.
            entity_b_id: Second entity identifier.
            entity_a_games: Game history for entity A.
            entity_b_games: Game history for entity B.

        Returns:
            Dict with ``entity_a_profile`` and ``entity_b_profile``.
        """
        a_agg = self.aggregate_player_history(entity_a_id, entity_a_games)
        b_agg = self.aggregate_player_history(entity_b_id, entity_b_games)
        return {
            "entity_a_profile": a_agg,
            "entity_b_profile": b_agg,
        }
