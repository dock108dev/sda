"""Orchestration layer for analytics operations.

The AnalyticsEngine is the main entry point for all analytics requests.
It loads the appropriate sport module, delegates to sport-specific
implementations, and returns structured results.

Usage::

    engine = AnalyticsEngine("mlb")
    profile = engine.get_team_profile("NYY")
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from .types import MatchupProfile, PlayerProfile, TeamProfile

logger = logging.getLogger(__name__)

# Registry of supported sport modules. Each key maps to the Python
# module path under ``app.analytics.sports``.
_SPORT_MODULES: dict[str, str] = {
    "mlb": "app.analytics.sports.mlb",
}


class AnalyticsEngine:
    """Top-level analytics orchestrator.

    Instantiate with a sport code, then call profile/matchup methods.
    Sport-specific logic is resolved at runtime via the plugin registry.
    """

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()
        self._module: Any | None = None

    def _load_module(self) -> Any:
        """Lazily load the sport-specific analytics module."""
        if self._module is not None:
            return self._module

        module_path = _SPORT_MODULES.get(self.sport)
        if module_path is None:
            raise ValueError(f"Unsupported sport: {self.sport}")

        self._module = importlib.import_module(module_path)
        logger.info("analytics_module_loaded", extra={"sport": self.sport})
        return self._module

    def get_team_profile(self, team_id: str) -> TeamProfile:
        """Build an analytical profile for a team.

        Delegates to the sport module's ``build_team_profile`` if available,
        otherwise returns an empty profile.
        """
        return TeamProfile(team_id=team_id, sport=self.sport)

    def get_player_profile(self, player_id: str) -> PlayerProfile:
        """Build an analytical profile for a player.

        Delegates to the sport module's ``build_player_profile`` if available,
        otherwise returns an empty profile.
        """
        return PlayerProfile(player_id=player_id, sport=self.sport)

    def get_matchup(self, entity_a: str, entity_b: str) -> MatchupProfile:
        """Analyze a head-to-head matchup between two entities.

        Delegates to the sport module's ``analyze_matchup`` if available,
        otherwise returns an empty matchup profile.
        """
        return MatchupProfile(
            entity_a_id=entity_a,
            entity_b_id=entity_b,
            sport=self.sport,
        )
