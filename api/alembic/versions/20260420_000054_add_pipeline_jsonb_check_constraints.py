"""Add Postgres CHECK constraints for pipeline-relevant JSONB columns.

Revision ID: pipeline_jsonb_checks_001
Revises: 20260419_000053
Create Date: 2026-04-20

Secondary guard: the primary validation is the SQLAlchemy event hooks in
api/app/db/jsonb_validators.py.  These constraints ensure that even direct
SQL writes (migrations, psql, ETL) cannot store a structurally wrong value.

Only top-level type (array vs object) is enforced here; full field-level
validation remains in the app layer (jsonb_registry.py Pydantic models).

Nullable columns use "col IS NULL OR jsonb_typeof(col) = '...'" so that
rows inserted before this migration (with NULL) remain valid.
"""

from __future__ import annotations

from alembic import op


revision = "pipeline_jsonb_checks_001"
down_revision = "20260419_000053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sports_game_stories.moments_json — nullable array
    op.execute(
        """
        ALTER TABLE sports_game_stories
            ADD CONSTRAINT ck_game_stories_moments_json_is_array
            CHECK (moments_json IS NULL OR jsonb_typeof(moments_json) = 'array')
        """
    )
    # sports_game_stories.blocks_json — nullable array
    op.execute(
        """
        ALTER TABLE sports_game_stories
            ADD CONSTRAINT ck_game_stories_blocks_json_is_array
            CHECK (blocks_json IS NULL OR jsonb_typeof(blocks_json) = 'array')
        """
    )
    # sports_game_pipeline_stages.output_json — nullable object
    op.execute(
        """
        ALTER TABLE sports_game_pipeline_stages
            ADD CONSTRAINT ck_pipeline_stages_output_json_is_object
            CHECK (output_json IS NULL OR jsonb_typeof(output_json) = 'object')
        """
    )
    # sports_game_pipeline_stages.logs_json — non-nullable, defaults '[]'
    op.execute(
        """
        ALTER TABLE sports_game_pipeline_stages
            ADD CONSTRAINT ck_pipeline_stages_logs_json_is_array
            CHECK (logs_json IS NULL OR jsonb_typeof(logs_json) = 'array')
        """
    )
    # sports_game_timeline_artifacts.timeline_json — non-nullable, defaults '[]'
    op.execute(
        """
        ALTER TABLE sports_game_timeline_artifacts
            ADD CONSTRAINT ck_timeline_artifacts_timeline_json_is_array
            CHECK (jsonb_typeof(timeline_json) = 'array')
        """
    )
    # sports_game_timeline_artifacts.game_analysis_json — non-nullable, defaults '{}'
    op.execute(
        """
        ALTER TABLE sports_game_timeline_artifacts
            ADD CONSTRAINT ck_timeline_artifacts_game_analysis_json_is_object
            CHECK (jsonb_typeof(game_analysis_json) = 'object')
        """
    )
    # sports_game_timeline_artifacts.summary_json — non-nullable, defaults '{}'
    op.execute(
        """
        ALTER TABLE sports_game_timeline_artifacts
            ADD CONSTRAINT ck_timeline_artifacts_summary_json_is_object
            CHECK (jsonb_typeof(summary_json) = 'object')
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sports_game_stories "
        "DROP CONSTRAINT IF EXISTS ck_game_stories_moments_json_is_array"
    )
    op.execute(
        "ALTER TABLE sports_game_stories "
        "DROP CONSTRAINT IF EXISTS ck_game_stories_blocks_json_is_array"
    )
    op.execute(
        "ALTER TABLE sports_game_pipeline_stages "
        "DROP CONSTRAINT IF EXISTS ck_pipeline_stages_output_json_is_object"
    )
    op.execute(
        "ALTER TABLE sports_game_pipeline_stages "
        "DROP CONSTRAINT IF EXISTS ck_pipeline_stages_logs_json_is_array"
    )
    op.execute(
        "ALTER TABLE sports_game_timeline_artifacts "
        "DROP CONSTRAINT IF EXISTS ck_timeline_artifacts_timeline_json_is_array"
    )
    op.execute(
        "ALTER TABLE sports_game_timeline_artifacts "
        "DROP CONSTRAINT IF EXISTS ck_timeline_artifacts_game_analysis_json_is_object"
    )
    op.execute(
        "ALTER TABLE sports_game_timeline_artifacts "
        "DROP CONSTRAINT IF EXISTS ck_timeline_artifacts_summary_json_is_object"
    )
