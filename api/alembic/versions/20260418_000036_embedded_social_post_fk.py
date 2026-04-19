"""Add trigger-based FK for embedded_social_post_id in sports_game_stories.blocks_json.

Revision ID: embedded_social_post_fk_001
Revises: game_phase_not_null_001
Create Date: 2026-04-18

Because embedded_social_post_id lives inside a JSONB column (blocks_json),
Postgres cannot enforce a declarative FK. Two triggers replicate FK semantics:

1. trg_validate_embedded_social_post_ids — BEFORE INSERT OR UPDATE on
   sports_game_stories: raises foreign_key_violation if any block's
   embedded_social_post_id is non-null and not found in team_social_posts.

2. trg_nullify_deleted_embedded_social_post — AFTER DELETE on
   team_social_posts: sets embedded_social_post_id to NULL in every
   blocks_json element that references the deleted row (SET NULL semantics).

Down: drops both triggers and their backing functions.
"""

from __future__ import annotations

from alembic import op

revision = "embedded_social_post_fk_001"
down_revision = "game_phase_not_null_001"
branch_labels = None
depends_on = None

_VALIDATE_FN = "fn_validate_embedded_social_post_ids"
_VALIDATE_TRIGGER = "trg_validate_embedded_social_post_ids"
_NULLIFY_FN = "fn_nullify_deleted_embedded_social_post"
_NULLIFY_TRIGGER = "trg_nullify_deleted_embedded_social_post"
_STORIES_TABLE = "sports_game_stories"
_SOCIAL_TABLE = "team_social_posts"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Validate trigger: raise on dangling reference at write time.     #
    # ------------------------------------------------------------------ #
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_VALIDATE_FN}()
        RETURNS TRIGGER AS $$
        DECLARE
            post_id BIGINT;
        BEGIN
            IF NEW.blocks_json IS NULL THEN
                RETURN NEW;
            END IF;

            FOR post_id IN
                SELECT (elem->>'embedded_social_post_id')::BIGINT
                FROM jsonb_array_elements(NEW.blocks_json) AS elem
                WHERE elem->>'embedded_social_post_id' IS NOT NULL
                  AND elem->>'embedded_social_post_id' != 'null'
            LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM {_SOCIAL_TABLE} WHERE id = post_id
                ) THEN
                    RAISE EXCEPTION
                        'embedded_social_post_id % does not exist in {_SOCIAL_TABLE}',
                        post_id
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute(f"""
        CREATE TRIGGER {_VALIDATE_TRIGGER}
            BEFORE INSERT OR UPDATE ON {_STORIES_TABLE}
            FOR EACH ROW
            EXECUTE FUNCTION {_VALIDATE_FN}();
    """)

    # ------------------------------------------------------------------ #
    # 2. SET NULL trigger: nullify references when social post is deleted.#
    # ------------------------------------------------------------------ #
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_NULLIFY_FN}()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE {_STORIES_TABLE}
            SET blocks_json = (
                SELECT jsonb_agg(
                    CASE
                        WHEN (elem->>'embedded_social_post_id')::BIGINT = OLD.id
                        THEN elem - 'embedded_social_post_id'
                             || jsonb_build_object('embedded_social_post_id', NULL)
                        ELSE elem
                    END
                )
                FROM jsonb_array_elements(blocks_json) AS elem
            )
            WHERE blocks_json IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(blocks_json) AS elem
                  WHERE (elem->>'embedded_social_post_id')::BIGINT = OLD.id
              );
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute(f"""
        CREATE TRIGGER {_NULLIFY_TRIGGER}
            AFTER DELETE ON {_SOCIAL_TABLE}
            FOR EACH ROW
            EXECUTE FUNCTION {_NULLIFY_FN}();
    """)


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS {_VALIDATE_TRIGGER} ON {_STORIES_TABLE}"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {_VALIDATE_FN}()")

    op.execute(
        f"DROP TRIGGER IF EXISTS {_NULLIFY_TRIGGER} ON {_SOCIAL_TABLE}"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {_NULLIFY_FN}()")
