"""Repair card feed artifact payload column schema drift.

Revision ID: 20260603_000077
Revises: 20260603_000076
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260603_000077"
down_revision = "20260603_000076"
branch_labels = None
depends_on = None

_TABLE = "sports_game_card_feed_artifacts"
_FEED_KEY = "feed_key"
_CURRENT_UNIQUE = "uq_sports_game_card_feed_artifacts_game_contract_key"
_GAME_INDEX = "idx_sports_game_card_feed_artifacts_game"
_GENERATED_AT_INDEX = "idx_sports_game_card_feed_artifacts_generated_at"
_CURRENT_UNIQUE_COLUMNS = ("game_id", "contract_version", _FEED_KEY)
_PAYLOAD_COLUMNS = (
    "game_json",
    "sections_json",
    "team_stats_json",
    "player_stats_json",
    "cards_json",
    "validation_issues_json",
)


def _jsonb_column(name: str, default: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text(default),
    )


def _repair_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("contract_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column(_FEED_KEY, sa.String(length=32), nullable=True),
        sa.Column(
            "generation_status",
            sa.String(length=32),
            nullable=False,
            server_default="ready",
        ),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("card_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_play_index", sa.Integer(), nullable=True),
        _jsonb_column("game_json", "'{}'::jsonb"),
        _jsonb_column("sections_json", "'[]'::jsonb"),
        _jsonb_column("team_stats_json", "'[]'::jsonb"),
        _jsonb_column("player_stats_json", "'[]'::jsonb"),
        _jsonb_column("cards_json", "'[]'::jsonb"),
        _jsonb_column("validation_issues_json", "'[]'::jsonb"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "generator_label",
            sa.String(length=64),
            nullable=False,
            server_default="schema_repair",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def _unique_constraints(inspector: sa.Inspector) -> dict[str, tuple[str, ...]]:
    constraints: dict[str, tuple[str, ...]] = {}
    for constraint in inspector.get_unique_constraints(_TABLE):
        name = constraint.get("name")
        if name:
            constraints[name] = tuple(constraint.get("column_names") or ())
    return constraints


def _index_names(inspector: sa.Inspector) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(_TABLE) if index.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = _column_names(inspector)
    missing_payload_columns = any(column_name not in columns for column_name in _PAYLOAD_COLUMNS)

    for column in _repair_columns():
        if column.name not in columns:
            op.add_column(_TABLE, column)

    inspector = sa.inspect(bind)
    columns = _column_names(inspector)

    if _FEED_KEY in columns:
        op.execute(
            sa.text(
                "UPDATE sports_game_card_feed_artifacts "
                "SET feed_key = 'default' "
                "WHERE feed_key IS NULL"
            )
        )
        op.alter_column(
            _TABLE,
            _FEED_KEY,
            existing_type=sa.String(length=32),
            nullable=False,
        )

    if missing_payload_columns and "source_hash" in columns:
        op.execute(sa.text("UPDATE sports_game_card_feed_artifacts SET source_hash = NULL"))

    inspector = sa.inspect(bind)
    unique_constraints = _unique_constraints(inspector)
    for name, column_names in unique_constraints.items():
        if (
            column_names == ("game_id", "contract_version")
            or (name == _CURRENT_UNIQUE and column_names != _CURRENT_UNIQUE_COLUMNS)
        ):
            op.drop_constraint(name, _TABLE, type_="unique")

    inspector = sa.inspect(bind)
    unique_constraints = _unique_constraints(inspector)
    if unique_constraints.get(_CURRENT_UNIQUE) != _CURRENT_UNIQUE_COLUMNS:
        op.create_unique_constraint(
            _CURRENT_UNIQUE,
            _TABLE,
            list(_CURRENT_UNIQUE_COLUMNS),
        )

    inspector = sa.inspect(bind)
    index_names = _index_names(inspector)
    if _GAME_INDEX not in index_names:
        op.create_index(_GAME_INDEX, _TABLE, ["game_id"])
    if _GENERATED_AT_INDEX not in index_names:
        op.create_index(_GENERATED_AT_INDEX, _TABLE, ["generated_at"])


def downgrade() -> None:
    """No-op: this revision repairs drift from the SSOT table migration."""
