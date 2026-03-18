"""Central matchup engine for comparing analytical profiles.

Routes matchup logic to sport-specific modules and returns structured
probability distributions. Designed for high-volume use in simulations
— all calculations are stateless, lightweight, and deterministic.

Usage::

    engine = MatchupEngine("mlb")
    result = engine.calculate_player_vs_player(batter_profile, pitcher_profile)
    # result.probabilities contains event probability distributions
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from .types import MatchupProfile, PlayerProfile, TeamProfile

logger = logging.getLogger(__name__)

# Registry mapping sport codes to (module_path, class_name).
_SPORT_MATCHUP: dict[str, tuple[str, str]] = {
    "mlb": ("app.analytics.sports.mlb.matchup", "MLBMatchup"),
}


class MatchupEngine:
    """Sport-agnostic matchup orchestrator.

    Loads the appropriate sport-specific matchup module and delegates
    probability calculations to it.
    """

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()
        self._matchup_instance: Any | None = None

    def _get_sport_matchup(self) -> Any:
        """Lazily load and cache the sport-specific matchup class."""
        if self._matchup_instance is not None:
            return self._matchup_instance

        entry = _SPORT_MATCHUP.get(self.sport)
        if entry is None:
            logger.warning("no_matchup_module", extra={"sport": self.sport})
            return None

        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        self._matchup_instance = cls()
        return self._matchup_instance

    def calculate_player_vs_player(
        self,
        player_a_profile: PlayerProfile,
        player_b_profile: PlayerProfile,
    ) -> MatchupProfile:
        """Compare two player profiles and produce a matchup analysis.

        For MLB this models batter-vs-pitcher probability distributions.

        Args:
            player_a_profile: First player (e.g., batter).
            player_b_profile: Second player (e.g., pitcher).

        Returns:
            MatchupProfile with probability distributions.
        """
        matchup = self._get_sport_matchup()
        if matchup is None:
            return self._empty_matchup(player_a_profile.player_id, player_b_profile.player_id)

        probabilities = matchup.batter_vs_pitcher(player_a_profile, player_b_profile)
        comparison = matchup.compare_metrics(player_a_profile, player_b_profile)
        advantages = matchup.determine_advantages(comparison)

        return MatchupProfile(
            entity_a_id=player_a_profile.player_id,
            entity_b_id=player_b_profile.player_id,
            sport=self.sport,
            comparison=comparison,
            advantages=advantages,
            probabilities=probabilities,
        )

    def calculate_team_vs_team(
        self,
        team_a_profile: TeamProfile,
        team_b_profile: TeamProfile,
    ) -> MatchupProfile:
        """Compare two team profiles and produce a matchup analysis.

        Args:
            team_a_profile: First team (e.g., home team).
            team_b_profile: Second team (e.g., away team).

        Returns:
            MatchupProfile with team-level probability distributions.
        """
        matchup = self._get_sport_matchup()
        if matchup is None:
            return self._empty_matchup(team_a_profile.team_id, team_b_profile.team_id)

        probabilities = matchup.team_offense_vs_pitching(team_a_profile, team_b_profile)

        return MatchupProfile(
            entity_a_id=team_a_profile.team_id,
            entity_b_id=team_b_profile.team_id,
            sport=self.sport,
            probabilities=probabilities,
        )

    def calculate_player_vs_team(
        self,
        player_profile: PlayerProfile,
        team_profile: TeamProfile,
    ) -> MatchupProfile:
        """Compare a player against a team profile.

        Useful for modeling a batter against a team's pitching staff.

        Args:
            player_profile: Individual player profile.
            team_profile: Team profile (pitching staff aggregate).

        Returns:
            MatchupProfile with probability distributions.
        """
        matchup = self._get_sport_matchup()
        if matchup is None:
            return self._empty_matchup(player_profile.player_id, team_profile.team_id)

        # Convert team metrics to a pseudo-pitcher profile for the matchup
        pitcher_proxy = PlayerProfile(
            player_id=team_profile.team_id,
            sport=self.sport,
            name=team_profile.name,
            metrics=team_profile.metrics,
        )
        probabilities = matchup.batter_vs_pitcher(player_profile, pitcher_proxy)

        return MatchupProfile(
            entity_a_id=player_profile.player_id,
            entity_b_id=team_profile.team_id,
            sport=self.sport,
            probabilities=probabilities,
        )

    def _empty_matchup(self, a_id: str, b_id: str) -> MatchupProfile:
        return MatchupProfile(entity_a_id=a_id, entity_b_id=b_id, sport=self.sport)
