"""DB index audit and benchmark tests for ISSUE-021.

Unit tests (always run):
- Validate migration 20260422_000066 declares expected index names
- Validate upgrade/downgrade symmetry

Integration benchmarks (require BENCHMARK_DB=1 env var + live PostgreSQL):
- Seed 10k pool entries and assert all five query paths execute in <50ms
- Verify pg_indexes has no duplicate or conflicting indexes on affected tables
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import time
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MIGRATION_FILENAME = "20260422_000066_add_query_performance_indexes.py"
_MIGRATION_PATH = (
    pathlib.Path(__file__).parent.parent
    / "alembic"
    / "versions"
    / _MIGRATION_FILENAME
)

_EXPECTED_INDEXES = {
    "ix_pool_entries_pool_id_score",
    "ix_golf_pools_club_id_status_created_at",
    "ix_golf_pools_status",
    "ix_club_claims_status",
    "ix_stripe_subscriptions_status",
}

# Mapping of index name → expected table
_INDEX_TABLES = {
    "ix_pool_entries_pool_id_score": "golf_pool_entry_scores",
    "ix_golf_pools_club_id_status_created_at": "golf_pools",
    "ix_golf_pools_status": "golf_pools",
    "ix_club_claims_status": "club_claims",
    "ix_stripe_subscriptions_status": "stripe_subscriptions",
}


def _load_migration() -> types.ModuleType:
    """Load the migration module from its file path."""
    spec = importlib.util.spec_from_file_location("migration_000066", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None, (
        f"Could not load migration from {_MIGRATION_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Unit tests — no database required
# ---------------------------------------------------------------------------


class TestMigrationStructure:
    """Validate migration file declares all expected indexes."""

    def test_migration_imports(self) -> None:
        mod = _load_migration()
        assert hasattr(mod, "upgrade")
        assert hasattr(mod, "downgrade")

    def test_revision_chain(self) -> None:
        mod = _load_migration()
        assert mod.revision == "20260422_000066"
        assert mod.down_revision == "20260421_000065"

    def test_upgrade_creates_all_expected_indexes(self) -> None:
        mod = _load_migration()
        created: list[str] = []

        mock_op = MagicMock()
        mock_op.create_index.side_effect = lambda name, *a, **kw: created.append(name)

        with patch.object(mod, "op", mock_op):
            mod.upgrade()

        assert set(created) == _EXPECTED_INDEXES, (
            f"upgrade() creates {set(created)} but expected {_EXPECTED_INDEXES}"
        )

    def test_upgrade_targets_correct_tables(self) -> None:
        mod = _load_migration()
        calls_by_name: dict[str, str] = {}

        mock_op = MagicMock()

        def _capture(name, table, *a, **kw):
            calls_by_name[name] = table

        mock_op.create_index.side_effect = _capture

        with patch.object(mod, "op", mock_op):
            mod.upgrade()

        for idx, expected_table in _INDEX_TABLES.items():
            assert calls_by_name.get(idx) == expected_table, (
                f"{idx} should target {expected_table!r}, got {calls_by_name.get(idx)!r}"
            )

    def test_downgrade_drops_all_indexes(self) -> None:
        mod = _load_migration()
        dropped: list[str] = []

        mock_op = MagicMock()
        mock_op.drop_index.side_effect = lambda name, **kw: dropped.append(name)

        with patch.object(mod, "op", mock_op):
            mod.downgrade()

        assert set(dropped) == _EXPECTED_INDEXES, (
            f"downgrade() drops {set(dropped)} but expected {_EXPECTED_INDEXES}"
        )

    def test_downgrade_is_inverse_of_upgrade(self) -> None:
        """Every index created in upgrade must be dropped in downgrade and vice versa."""
        mod = _load_migration()
        created: list[str] = []
        dropped: list[str] = []

        mock_op = MagicMock()
        mock_op.create_index.side_effect = lambda name, *a, **kw: created.append(name)
        mock_op.drop_index.side_effect = lambda name, **kw: dropped.append(name)

        with patch.object(mod, "op", mock_op):
            mod.upgrade()
            mod.downgrade()

        assert set(created) == set(dropped), (
            "Indexes created by upgrade() do not match indexes dropped by downgrade()"
        )

    def test_no_unique_indexes(self) -> None:
        """Performance indexes should not be declared unique (would add write overhead)."""
        mod = _load_migration()
        seen_unique: list[str] = []

        mock_op = MagicMock()

        def _check(name, table, cols, unique=False, **kw):
            if unique:
                seen_unique.append(name)

        mock_op.create_index.side_effect = _check

        with patch.object(mod, "op", mock_op):
            mod.upgrade()

        assert not seen_unique, f"These indexes should not be unique: {seen_unique}"

    def test_leaderboard_index_covers_sort_columns(self) -> None:
        """ix_pool_entries_pool_id_score must include pool_id, rank, and aggregate_score."""
        mod = _load_migration()
        cols_by_name: dict[str, list] = {}

        mock_op = MagicMock()

        def _capture(name, table, cols, *a, **kw):
            cols_by_name[name] = list(cols)

        mock_op.create_index.side_effect = _capture

        with patch.object(mod, "op", mock_op):
            mod.upgrade()

        leaderboard_cols = cols_by_name.get("ix_pool_entries_pool_id_score", [])
        assert "pool_id" in leaderboard_cols
        assert "rank" in leaderboard_cols
        assert "aggregate_score" in leaderboard_cols

    def test_club_dashboard_index_covers_filter_and_sort(self) -> None:
        """ix_golf_pools_club_id_status_created_at must cover club_id, status, created_at."""
        mod = _load_migration()
        cols_by_name: dict[str, list] = {}

        mock_op = MagicMock()

        def _capture(name, table, cols, *a, **kw):
            cols_by_name[name] = list(cols)

        mock_op.create_index.side_effect = _capture

        with patch.object(mod, "op", mock_op):
            mod.upgrade()

        dashboard_cols = cols_by_name.get("ix_golf_pools_club_id_status_created_at", [])
        assert "club_id" in dashboard_cols
        assert "status" in dashboard_cols
        assert "created_at" in dashboard_cols

    def test_migration_docstring_documents_all_five_paths(self) -> None:
        """Migration docstring must reference each of the five query-path labels."""
        mod = _load_migration()
        doc = mod.__doc__ or ""
        for path_label in [
            "leaderboard",
            "dashboard",
            "submission",
            "stats",
            "idempotency",
        ]:
            assert path_label in doc.lower(), (
                f"Migration docstring missing documentation for '{path_label}' query path"
            )


# ---------------------------------------------------------------------------
# Integration benchmarks — require BENCHMARK_DB=1 and a live PostgreSQL DB
# ---------------------------------------------------------------------------

_HAVE_BENCHMARK_DB = bool(os.getenv("BENCHMARK_DB"))
_SKIP_REASON = "Set BENCHMARK_DB=1 with a live PostgreSQL instance to run benchmarks"


@pytest.mark.skipif(not _HAVE_BENCHMARK_DB, reason=_SKIP_REASON)
class TestQueryBenchmarks:
    """Assert all five query paths run in <50ms on a 10k-entry dataset."""

    @pytest.fixture(scope="class")
    def db_session(self):
        """Provide a SQLAlchemy Session connected to the real test database."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        url = os.environ["DATABASE_URL"]
        engine = create_engine(url, echo=False)
        with Session(engine) as session:
            yield session

    @pytest.fixture(scope="class", autouse=True)
    def seed_data(self, db_session):
        """Insert 10k pool entries under a single test pool and clean up after."""
        import uuid
        from datetime import UTC, datetime

        from sqlalchemy import text

        session = db_session

        # Minimal club
        club_id = str(uuid.uuid4())
        session.execute(
            text(
                """
                INSERT INTO clubs (club_id, slug, name, plan_id, status, owner_user_id, created_at)
                VALUES (:cid, :slug, 'Bench Club', 'starter', 'active', 1, now())
                ON CONFLICT DO NOTHING
                """
            ),
            {"cid": club_id, "slug": f"bench-{club_id[:8]}"},
        )
        session.flush()

        club_row = session.execute(
            text("SELECT id FROM clubs WHERE club_id = :cid"), {"cid": club_id}
        ).fetchone()
        club_pk = club_row[0]

        # Minimal pool
        session.execute(
            text(
                """
                INSERT INTO golf_pools
                  (code, name, club_code, club_id, status, rules_json,
                   scoring_enabled, max_entries_per_email, created_at, updated_at)
                VALUES
                  ('bench-pool', 'Bench Pool', 'bench', :cid, 'open', '{}',
                   false, 100, now(), now())
                """
            ),
            {"cid": club_pk},
        )
        session.flush()

        pool_row = session.execute(
            text("SELECT id FROM golf_pools WHERE code = 'bench-pool' AND club_id = :cid"),
            {"cid": club_pk},
        ).fetchone()
        pool_id = pool_row[0]

        # 10k entries spread across 100 fake emails
        batch: list[dict] = []
        for i in range(10_000):
            email = f"user{i % 100}@benchmark.test"
            batch.append(
                {
                    "pool_id": pool_id,
                    "email": email,
                    "entry_name": f"Entry {i}",
                    "entry_number": (i // 100) + 1,
                    "status": "submitted",
                    "source": "self_service",
                    "submitted_at": datetime.now(UTC),
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            )
        session.execute(
            text(
                """
                INSERT INTO golf_pool_entries
                  (pool_id, email, entry_name, entry_number, status, source,
                   submitted_at, created_at, updated_at)
                VALUES
                  (:pool_id, :email, :entry_name, :entry_number, :status, :source,
                   :submitted_at, :created_at, :updated_at)
                """
            ),
            batch,
        )

        # 10k score rows (one per entry)
        entry_rows = session.execute(
            text("SELECT id FROM golf_pool_entries WHERE pool_id = :pid"), {"pid": pool_id}
        ).fetchall()
        score_batch = [
            {
                "pool_id": pool_id,
                "entry_id": row[0],
                "rank": idx + 1,
                "aggregate_score": -idx,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            for idx, row in enumerate(entry_rows)
        ]
        session.execute(
            text(
                """
                INSERT INTO golf_pool_entry_scores
                  (pool_id, entry_id, rank, aggregate_score, created_at, updated_at)
                VALUES
                  (:pool_id, :entry_id, :rank, :aggregate_score, :created_at, :updated_at)
                """
            ),
            score_batch,
        )
        session.commit()

        self._pool_id = pool_id
        self._club_pk = club_pk
        self._club_id = club_id

        yield

        # Cleanup
        session.execute(text("DELETE FROM golf_pool_entry_scores WHERE pool_id = :pid"), {"pid": pool_id})
        session.execute(text("DELETE FROM golf_pool_entries WHERE pool_id = :pid"), {"pid": pool_id})
        session.execute(text("DELETE FROM golf_pools WHERE id = :pid"), {"pid": pool_id})
        session.execute(text("DELETE FROM clubs WHERE id = :cid"), {"cid": club_pk})
        session.commit()

    def _time_query(self, db_session, sql: str, params: dict, *, label: str) -> float:
        from sqlalchemy import text

        start = time.perf_counter()
        db_session.execute(text(sql), params).fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"\n[benchmark] {label}: {elapsed_ms:.1f}ms")
        return elapsed_ms

    def test_path1_leaderboard_sort_under_50ms(self, db_session) -> None:
        elapsed = self._time_query(
            db_session,
            """
            SELECT s.*, e.email, e.entry_name
            FROM golf_pool_entry_scores s
            JOIN golf_pool_entries e ON e.id = s.entry_id
            WHERE s.pool_id = :pid
            ORDER BY s.rank ASC NULLS LAST, s.aggregate_score ASC NULLS LAST
            """,
            {"pid": self._pool_id},
            label="leaderboard sort",
        )
        assert elapsed < 50, f"Leaderboard sort took {elapsed:.1f}ms (limit 50ms)"

    def test_path2_club_dashboard_pool_list_under_50ms(self, db_session) -> None:
        elapsed = self._time_query(
            db_session,
            """
            SELECT p.*
            FROM golf_pools p
            WHERE p.club_id = :cid
              AND p.status IN ('open', 'locked', 'live')
            ORDER BY p.created_at DESC
            """,
            {"cid": self._club_pk},
            label="club dashboard pool list",
        )
        assert elapsed < 50, f"Club dashboard pool list took {elapsed:.1f}ms (limit 50ms)"

    def test_path3_entry_submission_lookup_under_50ms(self, db_session) -> None:
        elapsed = self._time_query(
            db_session,
            """
            SELECT COUNT(*), MAX(entry_number)
            FROM golf_pool_entries
            WHERE pool_id = :pid AND email = :email
            """,
            {"pid": self._pool_id, "email": "user0@benchmark.test"},
            label="entry submission lookup",
        )
        assert elapsed < 50, f"Entry submission lookup took {elapsed:.1f}ms (limit 50ms)"

    def test_path4_admin_stats_aggregate_under_50ms(self, db_session) -> None:
        elapsed = self._time_query(
            db_session,
            """
            SELECT COUNT(*) FROM golf_pools
            WHERE status IN ('open', 'locked', 'live', 'final')
            """,
            {},
            label="admin stats pool count",
        )
        assert elapsed < 50, f"Admin stats pool count took {elapsed:.1f}ms (limit 50ms)"

    def test_path5_webhook_idempotency_under_50ms(self, db_session) -> None:
        from sqlalchemy import text

        # Warm up the PK index then measure a no-op idempotency insert
        start = time.perf_counter()
        db_session.execute(
            text(
                """
                INSERT INTO processed_stripe_events (event_id, processed_at)
                VALUES ('bench-evt-001', now())
                ON CONFLICT DO NOTHING
                """
            )
        )
        db_session.rollback()
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"\n[benchmark] webhook idempotency insert: {elapsed_ms:.1f}ms")
        assert elapsed_ms < 50, f"Webhook idempotency insert took {elapsed_ms:.1f}ms (limit 50ms)"

    def test_no_duplicate_indexes_on_golf_pool_entry_scores(self, db_session) -> None:
        """Verify no two indexes on golf_pool_entry_scores share identical key columns."""
        from sqlalchemy import text

        rows = db_session.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'golf_pool_entry_scores'
                """
            )
        ).fetchall()

        # Extract column lists from indexdef (everything inside the last pair of parens)
        seen: dict[str, str] = {}
        for name, defn in rows:
            # Extract "ON table (cols)" → "cols"
            cols_part = defn[defn.rfind("(") + 1 : defn.rfind(")")]
            normalized = ",".join(c.strip() for c in cols_part.split(","))
            assert normalized not in seen, (
                f"Duplicate index columns '{normalized}' on golf_pool_entry_scores: "
                f"{seen[normalized]!r} and {name!r}"
            )
            seen[normalized] = name

    def test_no_duplicate_indexes_on_golf_pools(self, db_session) -> None:
        from sqlalchemy import text

        rows = db_session.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'golf_pools'")
        ).fetchall()

        seen: dict[str, str] = {}
        for name, defn in rows:
            cols_part = defn[defn.rfind("(") + 1 : defn.rfind(")")]
            normalized = ",".join(c.strip() for c in cols_part.split(","))
            assert normalized not in seen, (
                f"Duplicate index columns '{normalized}' on golf_pools: "
                f"{seen[normalized]!r} and {name!r}"
            )
            seen[normalized] = name
