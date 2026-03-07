"""Service layer connecting analytics logic to API endpoints.

Provides a clean interface for the router layer to call without
needing to know about engine internals or sport module resolution.
"""

from __future__ import annotations

from typing import Any

from app.analytics.core.analytics_engine import AnalyticsEngine
from app.analytics.core.simulation_engine import SimulationEngine
from app.analytics.core.types import (
    MatchupProfile,
    PlayerProfile,
    SimulationResult,
    TeamProfile,
)


class AnalyticsService:
    """High-level analytics service used by API routes."""

    def get_team_analysis(self, sport: str, team_id: str) -> TeamProfile:
        """Retrieve team analytical profile.

        Args:
            sport: Sport code (e.g., ``"mlb"``).
            team_id: Team identifier.

        Returns:
            Populated TeamProfile.
        """
        engine = AnalyticsEngine(sport)
        return engine.get_team_profile(team_id)

    def get_player_analysis(self, sport: str, player_id: str) -> PlayerProfile:
        """Retrieve player analytical profile.

        Args:
            sport: Sport code.
            player_id: Player identifier.

        Returns:
            Populated PlayerProfile.
        """
        engine = AnalyticsEngine(sport)
        return engine.get_player_profile(player_id)

    def get_matchup_analysis(
        self,
        sport: str,
        entity_a: str,
        entity_b: str,
    ) -> MatchupProfile:
        """Analyze a matchup between two entities.

        Args:
            sport: Sport code.
            entity_a: First entity identifier.
            entity_b: Second entity identifier.

        Returns:
            MatchupProfile with comparison data.
        """
        engine = AnalyticsEngine(sport)
        return engine.get_matchup(entity_a, entity_b)

    def run_simulation(
        self,
        sport: str,
        game_context: dict[str, Any],
        iterations: int = 1000,
    ) -> SimulationResult:
        """Run a game simulation.

        Args:
            sport: Sport code.
            game_context: Sport-specific game setup data.
            iterations: Number of simulation iterations.

        Returns:
            SimulationResult with outcome distribution.
        """
        sim = SimulationEngine(sport)
        return sim.simulate_game(game_context, iterations=iterations)
