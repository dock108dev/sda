"""MLB-specific training label extraction and record builders.

Provides label functions for plate-appearance and game models,
plus convenience record builders for constructing training data.

Data loading is handled by ``app.tasks._training_helpers`` which
queries the database directly. The stub loaders here exist only
as a fallback for the ``TrainingPipeline`` when no records are
passed; they return empty lists.
"""

from __future__ import annotations

import logging
from typing import Any

from app.analytics.datasets.mlb_pitch_labeler import PITCH_OUTCOME_LABELS
from app.analytics.models.sports.mlb.batted_ball_model import BATTED_BALL_OUTCOMES
from app.analytics.sports.mlb.constants import PA_EVENTS as PA_OUTCOMES

logger = logging.getLogger(__name__)


class MLBTrainingPipeline:
    """MLB-specific training label helpers and record builders."""

    def load_plate_appearance_training_data(self) -> list[dict[str, Any]]:
        """Stub — returns ``[]``.  Real loading is in ``_training_helpers``."""
        return []

    def load_game_training_data(self) -> list[dict[str, Any]]:
        """Stub — returns ``[]``.  Real loading is in ``_training_helpers``."""
        return []

    @staticmethod
    def pa_label_fn(record: dict[str, Any]) -> str | None:
        """Extract plate-appearance outcome label from a record."""
        outcome = record.get("outcome") or record.get("label")
        if outcome is None:
            return None
        outcome = str(outcome).lower().strip()
        if outcome in PA_OUTCOMES:
            return outcome
        return None

    @staticmethod
    def game_label_fn(record: dict[str, Any]) -> int | None:
        """Extract game outcome label from a record.

        Returns 1 for home win, 0 for away win.
        """
        if "home_win" in record:
            return int(record["home_win"])
        if "label" in record:
            return int(record["label"])
        home_score = record.get("home_score")
        away_score = record.get("away_score")
        if home_score is not None and away_score is not None:
            return 1 if home_score > away_score else 0
        return None

    @staticmethod
    def pitch_label_fn(record: dict[str, Any]) -> str | None:
        """Extract pitch outcome label from a record."""
        outcome = record.get("outcome") or record.get("label")
        if outcome is None:
            return None
        outcome = str(outcome).lower().strip()
        if outcome in PITCH_OUTCOME_LABELS:
            return outcome
        return None

    @staticmethod
    def batted_ball_label_fn(record: dict[str, Any]) -> str | None:
        """Extract batted ball outcome label from a record."""
        outcome = record.get("outcome") or record.get("label")
        if outcome is None:
            return None
        outcome = str(outcome).lower().strip()
        if outcome in BATTED_BALL_OUTCOMES:
            return outcome
        return None

    @staticmethod
    def build_pa_record(
        batter_metrics: dict[str, Any],
        pitcher_metrics: dict[str, Any],
        outcome: str,
    ) -> dict[str, Any]:
        """Build a training record for plate-appearance model."""
        return {
            "batter_profile": {"metrics": batter_metrics},
            "pitcher_profile": {"metrics": pitcher_metrics},
            "outcome": outcome,
        }

    @staticmethod
    def build_game_record(
        home_metrics: dict[str, Any],
        away_metrics: dict[str, Any],
        home_win: bool,
        *,
        home_score: int | None = None,
        away_score: int | None = None,
    ) -> dict[str, Any]:
        """Build a training record for game model."""
        record: dict[str, Any] = {
            "home_profile": {"metrics": home_metrics},
            "away_profile": {"metrics": away_metrics},
            "home_win": int(home_win),
        }
        if home_score is not None:
            record["home_score"] = home_score
        if away_score is not None:
            record["away_score"] = away_score
        return record
