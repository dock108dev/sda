"""SQLAlchemy mapper event hooks for all JSONB columns not covered by external_id_validators.

Imports from flow.py and sports.py models, then registers before_insert /
before_update listeners that call validate_jsonb_column() from the central
registry.  Import this module to activate the hooks (hooks.py does this at
startup).
"""

from __future__ import annotations

from sqlalchemy import event

from .flow import SportsGameFlow, SportsGameTimelineArtifact
from .jsonb_registry import validate_jsonb_column
from .sports import SportsGamePlay, SportsPlayerBoxscore, SportsTeamBoxscore


# ---------------------------------------------------------------------------
# SportsTeamBoxscore — raw_stats_json
# ---------------------------------------------------------------------------


@event.listens_for(SportsTeamBoxscore, "before_insert")
@event.listens_for(SportsTeamBoxscore, "before_update")
def _validate_team_boxscore_stats(mapper, connection, target: SportsTeamBoxscore) -> None:
    validate_jsonb_column("sports_team_boxscores", "raw_stats_json", target.stats)


# ---------------------------------------------------------------------------
# SportsPlayerBoxscore — raw_stats_json
# ---------------------------------------------------------------------------


@event.listens_for(SportsPlayerBoxscore, "before_insert")
@event.listens_for(SportsPlayerBoxscore, "before_update")
def _validate_player_boxscore_stats(
    mapper, connection, target: SportsPlayerBoxscore
) -> None:
    validate_jsonb_column("sports_player_boxscores", "raw_stats_json", target.stats)


# ---------------------------------------------------------------------------
# SportsGamePlay — raw_data
# ---------------------------------------------------------------------------


@event.listens_for(SportsGamePlay, "before_insert")
@event.listens_for(SportsGamePlay, "before_update")
def _validate_play_raw_data(mapper, connection, target: SportsGamePlay) -> None:
    validate_jsonb_column("sports_game_plays", "raw_data", target.raw_data)


# ---------------------------------------------------------------------------
# SportsGameFlow — moments_json, blocks_json
# ---------------------------------------------------------------------------


@event.listens_for(SportsGameFlow, "before_insert")
@event.listens_for(SportsGameFlow, "before_update")
def _validate_game_flow(mapper, connection, target: SportsGameFlow) -> None:
    validate_jsonb_column("sports_game_stories", "moments_json", target.moments_json)
    validate_jsonb_column("sports_game_stories", "blocks_json", target.blocks_json)


# ---------------------------------------------------------------------------
# SportsGameTimelineArtifact — timeline_json, game_analysis_json, summary_json
# ---------------------------------------------------------------------------


@event.listens_for(SportsGameTimelineArtifact, "before_insert")
@event.listens_for(SportsGameTimelineArtifact, "before_update")
def _validate_timeline_artifact(
    mapper, connection, target: SportsGameTimelineArtifact
) -> None:
    validate_jsonb_column(
        "sports_game_timeline_artifacts", "timeline_json", target.timeline_json
    )
    validate_jsonb_column(
        "sports_game_timeline_artifacts",
        "game_analysis_json",
        target.game_analysis_json,
    )
    validate_jsonb_column(
        "sports_game_timeline_artifacts", "summary_json", target.summary_json
    )


# ---------------------------------------------------------------------------
# GamePipelineStage — output_json, logs_json
#
# Registered lazily via Mapper.after_configured to avoid a circular import:
# db.pipeline → services.pipeline (package __init__) → executor → db.pipeline
# ---------------------------------------------------------------------------


def _validate_pipeline_stage(mapper, connection, target) -> None:
    validate_jsonb_column(
        "sports_game_pipeline_stages", "output_json", target.output_json
    )
    validate_jsonb_column(
        "sports_game_pipeline_stages", "logs_json", target.logs_json
    )


def _register_pipeline_stage_hooks() -> None:
    """Deferred hook registration — called after all mappers are configured."""
    from .pipeline import GamePipelineStage  # noqa: PLC0415

    event.listen(GamePipelineStage, "before_insert", _validate_pipeline_stage)
    event.listen(GamePipelineStage, "before_update", _validate_pipeline_stage)


from sqlalchemy.orm import Mapper as _Mapper  # noqa: E402

event.listen(_Mapper, "after_configured", _register_pipeline_stage_hooks, once=True)
