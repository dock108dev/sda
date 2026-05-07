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

    Active stage order (v3-summary pipeline):
    1. NORMALIZE_PBP      - Build normalized PBP events with phases
    2. CLASSIFY_GAME_SHAPE- Deterministic archetype classification (no LLM)
    3. GENERATE_SUMMARY   - Single LLM call producing 3-5 paragraph recap
    4. FINALIZE_SUMMARY   - Persist summary to sports_game_stories

    Legacy enum members (GENERATE_MOMENTS, VALIDATE_MOMENTS, ANALYZE_DRAMA,
    GROUP_BLOCKS, RENDER_BLOCKS, VALIDATE_BLOCKS, FINALIZE_MOMENTS) are kept
    so historical pipeline_runs rows still parse via ``PipelineStage(s.stage)``.
    They are not in ``ordered_stages()`` and the executor does not dispatch
    them.
    """

    # --- Active stages ---
    NORMALIZE_PBP = "NORMALIZE_PBP"
    CLASSIFY_GAME_SHAPE = "CLASSIFY_GAME_SHAPE"
    GENERATE_SUMMARY = "GENERATE_SUMMARY"
    FINALIZE_SUMMARY = "FINALIZE_SUMMARY"

    # --- Legacy stages (historical row compatibility only) ---
    GENERATE_MOMENTS = "GENERATE_MOMENTS"
    VALIDATE_MOMENTS = "VALIDATE_MOMENTS"
    ANALYZE_DRAMA = "ANALYZE_DRAMA"
    GROUP_BLOCKS = "GROUP_BLOCKS"
    RENDER_BLOCKS = "RENDER_BLOCKS"
    VALIDATE_BLOCKS = "VALIDATE_BLOCKS"
    FINALIZE_MOMENTS = "FINALIZE_MOMENTS"

    @classmethod
    def ordered_stages(cls) -> list[PipelineStage]:
        """Return active stages in execution order."""
        return [
            cls.NORMALIZE_PBP,
            cls.CLASSIFY_GAME_SHAPE,
            cls.GENERATE_SUMMARY,
            cls.FINALIZE_SUMMARY,
        ]

    def next_stage(self) -> PipelineStage | None:
        """Return the next stage in the pipeline, or None if this is the last.

        ``stages.index(self)`` raises ``ValueError`` if called on a legacy
        stage that is no longer in ``ordered_stages()``. Callers iterating
        over historical runs should guard with ``stage in ordered_stages()``.
        """
        stages = self.ordered_stages()
        idx = stages.index(self)
        if idx < len(stages) - 1:
            return stages[idx + 1]
        return None

    def previous_stage(self) -> PipelineStage | None:
        """Return the previous stage in the pipeline, or None if this is the first."""
        stages = self.ordered_stages()
        idx = stages.index(self)
        if idx > 0:
            return stages[idx - 1]
        return None
