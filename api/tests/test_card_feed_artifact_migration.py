from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260603_000077_repair_card_feed_artifacts_payload_columns.py"
)
_SPOILER_POLICY_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260603_000078_remove_card_feed_artifact_spoiler_policy.py"
)


class _Inspector:
    def __init__(
        self,
        columns: set[str],
        *,
        unique_constraints: list[dict[str, object]] | None = None,
        indexes: list[dict[str, object]] | None = None,
    ) -> None:
        self._columns = columns
        self._unique_constraints = unique_constraints or []
        self._indexes = indexes or []

    def get_columns(self, table_name: str) -> list[dict[str, object]]:
        assert table_name == "sports_game_card_feed_artifacts"
        return [{"name": column_name} for column_name in self._columns]

    def get_unique_constraints(self, table_name: str) -> list[dict[str, object]]:
        assert table_name == "sports_game_card_feed_artifacts"
        return self._unique_constraints

    def get_indexes(self, table_name: str) -> list[dict[str, object]]:
        assert table_name == "sports_game_card_feed_artifacts"
        return self._indexes


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_20260603_000077", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_spoiler_policy_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_20260603_000078",
        _SPOILER_POLICY_MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repair_migration_adds_missing_payload_columns_and_invalidates_cache() -> None:
    migration = _load_migration()
    existing_columns = {
        "id",
        "game_id",
        "contract_version",
        "feed_key",
        "generation_status",
        "source_hash",
        "card_count",
        "last_play_index",
        "game_json",
        "sections_json",
        "cards_json",
        "validation_issues_json",
        "generated_at",
        "generator_label",
        "created_at",
        "updated_at",
    }
    repaired_columns = existing_columns | {"team_stats_json", "player_stats_json"}
    inspectors = [
        _Inspector(existing_columns),
        _Inspector(repaired_columns),
        _Inspector(repaired_columns),
        _Inspector(repaired_columns),
        _Inspector(repaired_columns),
    ]
    mock_op = MagicMock()
    mock_op.get_bind.return_value = object()

    with (
        patch.object(migration, "op", mock_op),
        patch.object(migration.sa, "inspect", side_effect=inspectors),
    ):
        migration.upgrade()

    added_columns = [call.args[1].name for call in mock_op.add_column.call_args_list]
    assert added_columns == ["team_stats_json", "player_stats_json"]
    executed_sql = [str(call.args[0]) for call in mock_op.execute.call_args_list]
    assert any("SET source_hash = NULL" in sql for sql in executed_sql)


def test_repair_migration_downgrade_is_not_destructive() -> None:
    migration = _load_migration()
    mock_op = MagicMock()

    with patch.object(migration, "op", mock_op):
        migration.downgrade()

    mock_op.drop_column.assert_not_called()
    mock_op.drop_constraint.assert_not_called()
    mock_op.drop_index.assert_not_called()


def test_spoiler_policy_migration_drops_legacy_card_feed_artifact_column() -> None:
    migration = _load_spoiler_policy_migration()
    mock_op = MagicMock()
    mock_op.get_bind.return_value = object()

    with (
        patch.object(migration, "op", mock_op),
        patch.object(
            migration.sa,
            "inspect",
            return_value=_Inspector({"id", "game_id", "spoiler_policy"}),
        ),
    ):
        migration.upgrade()

    mock_op.drop_column.assert_called_once_with(
        "sports_game_card_feed_artifacts",
        "spoiler_policy",
    )


def test_spoiler_policy_migration_noops_when_column_is_absent() -> None:
    migration = _load_spoiler_policy_migration()
    mock_op = MagicMock()
    mock_op.get_bind.return_value = object()

    with (
        patch.object(migration, "op", mock_op),
        patch.object(migration.sa, "inspect", return_value=_Inspector({"id", "game_id"})),
    ):
        migration.upgrade()

    mock_op.drop_column.assert_not_called()
