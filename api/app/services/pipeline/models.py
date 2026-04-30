"""Pipeline models and data structures.

This module defines the core data structures used by the pipeline executor
and individual stage implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from ...db.pipeline_stage import PipelineStage


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
    phase_boundaries: dict[str, tuple[str, str]]  # phase -> (start, end) ISO datetimes

    def to_dict(self) -> dict[str, Any]:
        return {
            "pbp_events": self.pbp_events,
            "game_start": self.game_start,
            "game_end": self.game_end,
            "has_overtime": self.has_overtime,
            "total_plays": self.total_plays,
            "phase_boundaries": self.phase_boundaries,
        }


@dataclass
class GeneratedMomentsOutput:
    """Output schema for GENERATE_MOMENTS stage.

    Contains the partitioned moments with all metadata, plus a full
    generation trace for explainability.
    """

    moments: list[dict[str, Any]]
    notable_moments: list[dict[str, Any]]
    moment_count: int
    budget: int
    within_budget: bool
    # Generation trace for explainability
    generation_trace: dict[str, Any] | None = None
    moment_distribution: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "moments": self.moments,
            "notable_moments": self.notable_moments,
            "moment_count": self.moment_count,
            "budget": self.budget,
            "within_budget": self.within_budget,
        }
        if self.generation_trace is not None:
            result["generation_trace"] = self.generation_trace
        if self.moment_distribution is not None:
            result["moment_distribution"] = self.moment_distribution
        return result


class QualityStatus(str, Enum):
    """Quality status of the validated moments.

    This provides a clear signal about data integrity beyond pass/fail.
    """

    PASSED = "PASSED"  # All checks passed, no issues
    DEGRADED = "DEGRADED"  # Passed with known issues (e.g., score discontinuity in non-strict mode)
    FAILED = "FAILED"  # Critical validation failures
    OVERRIDDEN = "OVERRIDDEN"  # Would have failed but manually overridden


@dataclass
class ScoreContinuityOverride:
    """Audit record for manual score continuity override.

    When score continuity issues are manually overridden, this captures
    the override metadata for auditability.
    """

    enabled: bool = False
    reason: str | None = None
    overridden_by: str | None = None
    overridden_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "reason": self.reason,
            "overridden_by": self.overridden_by,
            "overridden_at": self.overridden_at,
        }


@dataclass
class ValidationOutput:
    """Output schema for VALIDATE_MOMENTS stage.

    Contains the validation report and pass/fail status.
    """

    passed: bool
    critical_passed: bool
    warnings_count: int
    errors: list[str]
    warnings: list[str]
    validation_details: dict[str, Any]
    # Quality status provides clearer signal than just pass/fail
    quality_status: QualityStatus = QualityStatus.PASSED
    # Score continuity specific tracking
    score_continuity_issues: list[dict[str, Any]] = field(default_factory=list)
    score_continuity_override: ScoreContinuityOverride | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "passed": self.passed,
            "critical_passed": self.critical_passed,
            "warnings_count": self.warnings_count,
            "errors": self.errors,
            "warnings": self.warnings,
            "validation_details": self.validation_details,
            "quality_status": self.quality_status.value,
            "score_continuity_issues": self.score_continuity_issues,
        }
        if self.score_continuity_override:
            result["score_continuity_override"] = (
                self.score_continuity_override.to_dict()
            )
        return result


@dataclass
class FinalizedOutput:
    """Output schema for FINALIZE_MOMENTS stage.

    Contains references to the persisted artifact.
    """

    artifact_id: int
    timeline_events: int
    moment_count: int
    generated_at: str  # ISO format datetime
    quality_status: str = "PASSED"
    moment_distribution: dict[str, Any] | None = None
    block_count: int | None = None
    blocks_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "artifact_id": self.artifact_id,
            "timeline_events": self.timeline_events,
            "moment_count": self.moment_count,
            "generated_at": self.generated_at,
            "quality_status": self.quality_status,
        }
        if self.moment_distribution:
            result["moment_distribution"] = self.moment_distribution
        if self.block_count is not None:
            result["block_count"] = self.block_count
        if self.blocks_version is not None:
            result["blocks_version"] = self.blocks_version
        return result


@dataclass
class GroupBlocksOutput:
    """Output schema for GROUP_BLOCKS stage.

    Contains the grouped blocks with metadata for validation.
    """

    blocks: list[dict[str, Any]]
    block_count: int
    total_moments: int
    lead_changes: int
    largest_run: int
    split_points: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks": self.blocks,
            "block_count": self.block_count,
            "total_moments": self.total_moments,
            "lead_changes": self.lead_changes,
            "largest_run": self.largest_run,
            "split_points": self.split_points,
        }


@dataclass
class RenderBlocksOutput:
    """Output schema for RENDER_BLOCKS stage.

    Contains blocks with narratives and rendering statistics.
    """

    blocks: list[dict[str, Any]]
    block_count: int
    total_words: int
    openai_calls: int
    errors: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks": self.blocks,
            "block_count": self.block_count,
            "total_words": self.total_words,
            "openai_calls": self.openai_calls,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class ValidateBlocksOutput:
    """Output schema for VALIDATE_BLOCKS stage.

    Contains validation results for blocks.
    """

    passed: bool
    block_count: int
    total_words: int
    errors: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "block_count": self.block_count,
            "total_words": self.total_words,
            "errors": self.errors,
            "warnings": self.warnings,
        }
