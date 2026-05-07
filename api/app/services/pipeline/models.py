"""Pipeline models and data structures.

This module defines the core data structures used by the pipeline executor
and individual stage implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ...db.pipeline_stage import PipelineStage

__all__ = [
    "PipelineStage",
    "StageInput",
    "StageOutput",
    "StageResult",
    "NormalizedPBPOutput",
]


@dataclass
class StageInput:
    """Input data for a pipeline stage.

    Attributes:
        game_id: The game being processed
        run_id: The pipeline run ID
        previous_output: Output from the previous stage (None for first stage)
        game_context: Game metadata for team name resolution
    """

    game_id: int
    run_id: int
    previous_output: dict[str, Any] | None = None
    game_context: dict[str, str] = field(default_factory=dict)


@dataclass
class StageOutput:
    """Output data from a pipeline stage.

    Attributes:
        data: Stage-specific output data (stored in output_json)
        logs: Log entries generated during execution
    """

    data: dict[str, Any]
    logs: list[dict[str, Any]] = field(default_factory=list)

    def add_log(self, message: str, level: str = "info") -> None:
        """Add a log entry."""
        self.logs.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": level,
                "message": message,
            }
        )


@dataclass
class StageResult:
    """Result of executing a pipeline stage.

    Attributes:
        stage: The stage that was executed
        success: Whether the stage completed successfully
        output: Stage output data (None if failed)
        error: Error message if failed
        duration_seconds: Time taken to execute the stage
    """

    stage: PipelineStage
    success: bool
    output: StageOutput | None = None
    error: str | None = None
    duration_seconds: float = 0.0

    @property
    def failed(self) -> bool:
        return not self.success


@dataclass
class NormalizedPBPOutput:
    """Output schema for NORMALIZE_PBP stage.

    Contains the normalized play-by-play events with phase assignments
    and synthetic timestamps.
    """

    pbp_events: list[dict[str, Any]]
    game_start: str  # ISO format datetime
    game_end: str  # ISO format datetime
    has_overtime: bool
    total_plays: int
    phase_boundaries: dict[str, tuple[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pbp_events": self.pbp_events,
            "game_start": self.game_start,
            "game_end": self.game_end,
            "has_overtime": self.has_overtime,
            "total_plays": self.total_plays,
            "phase_boundaries": self.phase_boundaries,
        }
