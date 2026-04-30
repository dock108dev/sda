"""Pipeline stage enum (DB / ORM layer).

Lives in ``app.db`` so ``app.db.pipeline`` can import it without pulling in
``app.services.pipeline`` (which loads the executor and heavy transitive deps).
Callers and ``app.services.pipeline.models`` re-export the same type.
"""

from __future__ import annotations

from enum import Enum


class PipelineStage(str, Enum):
    """Pipeline stages for game processing.

    Stages are executed in order. Each stage consumes the output of the
    previous stage and produces output for the next stage.

    Stage order:
    1. NORMALIZE_PBP - Build normalized PBP events with phases
    2. GENERATE_MOMENTS - Partition game into narrative moments
    3. VALIDATE_MOMENTS - Run validation checks on moments
    4. ANALYZE_DRAMA - Use AI to identify game's dramatic peak and weight quarters
    5. GROUP_BLOCKS - Group moments into 4-7 narrative blocks (drama-weighted)
    6. RENDER_BLOCKS - Generate short narratives for each block
    7. VALIDATE_BLOCKS - Validate block constraints
    8. FINALIZE_MOMENTS - Persist final game flow artifact
    """

    NORMALIZE_PBP = "NORMALIZE_PBP"
    GENERATE_MOMENTS = "GENERATE_MOMENTS"
    VALIDATE_MOMENTS = "VALIDATE_MOMENTS"
    ANALYZE_DRAMA = "ANALYZE_DRAMA"
    GROUP_BLOCKS = "GROUP_BLOCKS"
    RENDER_BLOCKS = "RENDER_BLOCKS"
    VALIDATE_BLOCKS = "VALIDATE_BLOCKS"
    FINALIZE_MOMENTS = "FINALIZE_MOMENTS"

    @classmethod
    def ordered_stages(cls) -> list[PipelineStage]:
        """Return stages in execution order."""
        return [
            cls.NORMALIZE_PBP,
            cls.GENERATE_MOMENTS,
            cls.VALIDATE_MOMENTS,
            cls.ANALYZE_DRAMA,
            cls.GROUP_BLOCKS,
            cls.RENDER_BLOCKS,
            cls.VALIDATE_BLOCKS,
            cls.FINALIZE_MOMENTS,
        ]

    def next_stage(self) -> PipelineStage | None:
        """Return the next stage in the pipeline, or None if this is the last."""
        stages = self.ordered_stages()
        try:
            idx = stages.index(self)
            if idx < len(stages) - 1:
                return stages[idx + 1]
            return None
        except ValueError:
            return None

    def previous_stage(self) -> PipelineStage | None:
        """Return the previous stage in the pipeline, or None if this is the first."""
        stages = self.ordered_stages()
        try:
            idx = stages.index(self)
            if idx > 0:
                return stages[idx - 1]
            return None
        except ValueError:
            return None
