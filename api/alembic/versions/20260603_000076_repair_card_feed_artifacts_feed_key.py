"""Repair card feed artifact feed key schema drift.

Revision ID: 20260603_000076
Revises: 20260601_000075
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260603_000076"
down_revision = "20260601_000075"
branch_labels = None
depends_on = None

_TABLE = "sports_game_card_feed_artifacts"
_FEED_KEY = "feed_key"
_CURRENT_UNIQUE = "uq_sports_game_card_feed_artifacts_game_contract_key"
_GAME_INDEX = "idx_sports_game_card_feed_artifacts_game"
_GENERATED_AT_INDEX = "idx_sports_game_card_feed_artifacts_generated_at"


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

    if _FEED_KEY not in columns:
        op.add_column(_TABLE, sa.Column(_FEED_KEY, sa.String(length=32), nullable=True))
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

    inspector = sa.inspect(bind)
    unique_constraints = _unique_constraints(inspector)
    for name, column_names in unique_constraints.items():
        if column_names == ("game_id", "contract_version") and name != _CURRENT_UNIQUE:
            op.drop_constraint(name, _TABLE, type_="unique")

    inspector = sa.inspect(bind)
    unique_constraints = _unique_constraints(inspector)
    if unique_constraints.get(_CURRENT_UNIQUE) != (
        "game_id",
        "contract_version",
        _FEED_KEY,
    ):
        op.create_unique_constraint(
            _CURRENT_UNIQUE,
            _TABLE,
            ["game_id", "contract_version", _FEED_KEY],
        )

    inspector = sa.inspect(bind)
    index_names = _index_names(inspector)
    if _GAME_INDEX not in index_names:
        op.create_index(_GAME_INDEX, _TABLE, ["game_id"])
    if _GENERATED_AT_INDEX not in index_names:
        op.create_index(_GENERATED_AT_INDEX, _TABLE, ["generated_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = _column_names(inspector)
    index_names = _index_names(inspector)
    unique_constraints = _unique_constraints(inspector)

    if _GENERATED_AT_INDEX in index_names:
        op.drop_index(_GENERATED_AT_INDEX, table_name=_TABLE)
    if _GAME_INDEX in index_names:
        op.drop_index(_GAME_INDEX, table_name=_TABLE)
    if _CURRENT_UNIQUE in unique_constraints:
        op.drop_constraint(_CURRENT_UNIQUE, _TABLE, type_="unique")
    if _FEED_KEY in columns:
        op.drop_column(_TABLE, _FEED_KEY)
