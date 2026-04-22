"""Unit tests for streamed CSV export of pool entries.

GET /api/golf/pools/{pool_id}/export/entries.csv

Verifies:
- Response streams with correct Content-Type and headers
- Entries are fetched in batches of at most 500 rows
- Column headers match documented schema
- Empty pool returns header row only (HTTP 200)
- Non-admin request returns 403
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.db import get_db
from app.routers.golf import router
from app.routers.golf.pools_admin import _CSV_BATCH


# ---------------------------------------------------------------------------
# Test fixtures / factories
# ---------------------------------------------------------------------------


def _make_pool(pick_count: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        code="test-pool",
        name="Test Pool",
        club_code="rvcc",
        rules_json={"pick_count": pick_count},
    )


def _make_entry(entry_id: int, email: str = "user@example.com") -> SimpleNamespace:
    return SimpleNamespace(
        id=entry_id,
        pool_id=1,
        email=email,
        submitted_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


def _make_pick(entry_id: int, slot: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id=entry_id,
        pick_slot=slot,
        player_name_snapshot=name,
        dg_id=slot * 100,
    )


def _make_score(entry_id: int, score: int | None = -5) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id=entry_id,
        aggregate_score=score,
    )


class _FakeResult:
    """Minimal stand-in for SQLAlchemy AsyncResult."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._items)


def _make_db(
    pool: GolfPool,
    entry_batches: list[list[GolfPoolEntry]],
    picks_per_batch: list[list[GolfPoolEntryPick]] | None = None,
    scores_per_batch: list[list[GolfPoolEntryScore]] | None = None,
) -> MagicMock:
    """Build a fake async DB session.

    execute() is called in groups of 3 per non-empty batch:
    (1) entries, (2) picks for those entries, (3) scores for those entries.
    A final extra entries call returns [] to terminate the loop.
    """
    if picks_per_batch is None:
        picks_per_batch = [[] for _ in entry_batches]
    if scores_per_batch is None:
        scores_per_batch = [[] for _ in entry_batches]

    # Build the ordered side_effect list: each non-empty batch = 3 calls;
    # then a final empty-entries call to end the loop.
    side_effects: list[_FakeResult] = []
    for i, batch in enumerate(entry_batches):
        side_effects.append(_FakeResult(batch))
        side_effects.append(_FakeResult(picks_per_batch[i]))
        side_effects.append(_FakeResult(scores_per_batch[i]))
    # Terminal empty-batch call (ends the while-True loop)
    side_effects.append(_FakeResult([]))

    db = AsyncMock()
    db.get = AsyncMock(return_value=pool)
    db.execute = AsyncMock(side_effect=side_effects)
    return db


def _make_app(db: MagicMock, *, bypass_auth: bool = True) -> TestClient:
    """Build a TestClient backed by the given fake DB.

    bypass_auth=True (default) overrides require_admin to always pass.
    bypass_auth=False uses the real dependency (no JWT/API key → 403).
    """
    from app.dependencies.roles import require_admin

    app = FastAPI()

    async def _get_db_override():
        yield db

    app.dependency_overrides[get_db] = _get_db_override

    if bypass_auth:
        app.dependency_overrides[require_admin] = lambda: "admin"

    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_csv(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text))
    return list(reader)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStreamEntriesCsvHeaders:
    def test_content_type_is_text_csv(self) -> None:
        pool = _make_pool(pick_count=2)
        db = _make_db(pool, [[]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_content_disposition_header(self) -> None:
        pool = _make_pool(pick_count=2)
        db = _make_db(pool, [[]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "test-pool" in resp.headers["content-disposition"]

    def test_accel_buffering_disabled(self) -> None:
        pool = _make_pool(pick_count=2)
        db = _make_db(pool, [[]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert resp.headers.get("x-accel-buffering") == "no"


class TestStreamEntriesCsvColumns:
    def test_header_row_matches_schema(self) -> None:
        pool = _make_pool(pick_count=3)
        db = _make_db(pool, [[]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        rows = _parse_csv(resp.text)
        assert rows[0] == ["entry_id", "user_email", "pick_1", "pick_2", "pick_3", "submitted_at", "score"]

    def test_pick_columns_scale_with_pick_count(self) -> None:
        pool = _make_pool(pick_count=7)
        db = _make_db(pool, [[]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        rows = _parse_csv(resp.text)
        expected_picks = [f"pick_{i}" for i in range(1, 8)]
        assert rows[0] == ["entry_id", "user_email", *expected_picks, "submitted_at", "score"]


class TestStreamEntriesCsvEmptyPool:
    def test_empty_pool_returns_header_only(self) -> None:
        pool = _make_pool(pick_count=2)
        db = _make_db(pool, [[]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == 1, "Expected only the header row for an empty pool"
        assert rows[0][0] == "entry_id"


class TestStreamEntriesCsvData:
    def test_entry_data_in_rows(self) -> None:
        pool = _make_pool(pick_count=2)
        entry = _make_entry(42, "alice@example.com")
        pick1 = _make_pick(42, 1, "Tiger Woods")
        pick2 = _make_pick(42, 2, "Rory McIlroy")
        score = _make_score(42, -8)

        db = _make_db(pool, [[entry]], [[pick1, pick2]], [[score]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        rows = _parse_csv(resp.text)
        assert len(rows) == 2  # header + 1 data row
        data = rows[1]
        assert data[0] == "42"
        assert data[1] == "alice@example.com"
        assert data[2] == "Tiger Woods"
        assert data[3] == "Rory McIlroy"
        assert "2026-04-01" in data[4]  # submitted_at
        assert data[5] == "-8"

    def test_missing_picks_written_as_empty(self) -> None:
        pool = _make_pool(pick_count=3)
        entry = _make_entry(10)
        score = _make_score(10, 0)

        db = _make_db(pool, [[entry]], [[]], [[score]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        rows = _parse_csv(resp.text)
        data = rows[1]
        assert data[2] == ""
        assert data[3] == ""
        assert data[4] == ""

    def test_missing_score_written_as_empty(self) -> None:
        pool = _make_pool(pick_count=1)
        entry = _make_entry(5)

        db = _make_db(pool, [[entry]], [[]], [[]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        rows = _parse_csv(resp.text)
        assert rows[1][-1] == ""  # score column

    def test_null_aggregate_score_written_as_empty(self) -> None:
        pool = _make_pool(pick_count=1)
        entry = _make_entry(7)
        score = _make_score(7, None)

        db = _make_db(pool, [[entry]], [[]], [[score]])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        rows = _parse_csv(resp.text)
        assert rows[1][-1] == ""


class TestStreamEntriesCsvBatching:
    def test_1000_entries_fetched_in_two_batches(self) -> None:
        """Verifies that a 1000-entry pool is queried in ≤500-row batches."""
        pool = _make_pool(pick_count=1)
        batch1 = [_make_entry(i) for i in range(1, _CSV_BATCH + 1)]
        batch2 = [_make_entry(i) for i in range(_CSV_BATCH + 1, 2 * _CSV_BATCH + 1)]

        db = _make_db(pool, [batch1, batch2])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        # header + 1000 data rows
        assert len(rows) == 1001

        # execute was called: 3 calls × 2 non-empty batches + 1 terminal empty = 7
        assert db.execute.call_count == 7

    def test_batch_size_constant_is_500(self) -> None:
        assert _CSV_BATCH == 500

    def test_exact_500_entries_uses_single_batch_plus_terminal(self) -> None:
        pool = _make_pool(pick_count=1)
        batch = [_make_entry(i) for i in range(1, _CSV_BATCH + 1)]

        db = _make_db(pool, [batch])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == _CSV_BATCH + 1  # header + 500

        # 3 calls for the batch + 1 terminal empty = 4
        assert db.execute.call_count == 4

    def test_499_entries_uses_single_batch_no_terminal(self) -> None:
        """Fewer than batch-size entries stops without an extra empty query."""
        pool = _make_pool(pick_count=1)
        batch = [_make_entry(i) for i in range(1, _CSV_BATCH)]  # 499

        db = _make_db(pool, [batch])
        client = _make_app(db)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert resp.status_code == 200
        # Loop breaks when len(batch) < _CSV_BATCH, no terminal query needed
        assert db.execute.call_count == 3


class TestStreamEntriesCsvAuth:
    def test_non_admin_returns_403(self) -> None:
        """Requests without admin credentials must be rejected with 403."""
        pool = _make_pool(pick_count=2)
        db = _make_db(pool, [[]])

        # Do NOT bypass auth — real require_admin dependency applies.
        # No JWT token + no API key → resolve_role returns "guest" → 403.
        client = _make_app(db, bypass_auth=False)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert resp.status_code == 403

    def test_admin_role_override_returns_200(self) -> None:
        pool = _make_pool(pick_count=2)
        db = _make_db(pool, [[]])
        client = _make_app(db, bypass_auth=True)

        resp = client.get("/api/golf/pools/1/export/entries.csv")

        assert resp.status_code == 200
