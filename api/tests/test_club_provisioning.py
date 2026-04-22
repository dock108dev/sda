"""Tests for ClubProvisioningService and POST /api/admin/clubs/{claim_id}/provision.

Coverage requirements:
  - 100% branch coverage on provisioning transaction logic (DESIGN.md)
  - Integration-style concurrent test demonstrating ON CONFLICT DO NOTHING semantics
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.club import Club
from app.db.golf_pools import GolfPool
from app.db.onboarding import ClubClaim, OnboardingSession
from app.db.users import User
from app.routers.admin.clubs import router
from app.services.provisioning import (
    ClubProvisioningService,
    ProvisioningError,
    _derive_slug,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_result(
    scalar: Any = None,
    scalar_one: Any = None,
    rowcount: int | None = None,
) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalar_one.return_value = scalar_one if scalar_one is not None else scalar
    if rowcount is not None:
        r.rowcount = rowcount
    return r


def _make_session(status: str = "claimed", plan_id: str = "price_pro") -> OnboardingSession:
    return OnboardingSession(
        claim_id="claim_abc",
        session_token="sess_xyz",
        stripe_checkout_session_id="cs_test_001",
        plan_id=plan_id,
        status=status,
    )


def _make_claim(
    club_name: str = "Pebble Beach GC",
    email: str = "pro@pebble.example",
) -> ClubClaim:
    return ClubClaim(
        claim_id="claim_abc",
        club_name=club_name,
        contact_email=email,
        status="new",
    )


def _make_user(user_id: int = 42) -> User:
    u = User(email="pro@pebble.example", role="club_admin", is_active=True)
    u.id = user_id
    return u


def _make_club(
    slug: str = "pebble-beach-gc",
    club_id: str = "uuid-1111",
    owner_user_id: int | None = 42,
    db_id: int = 1,
) -> Club:
    c = Club(
        club_id=club_id,
        slug=slug,
        name="Pebble Beach GC",
        plan_id="price_pro",
        status="active",
        owner_user_id=owner_user_id,
    )
    c.id = db_id
    return c


class _QueueDB:
    """Async session stub that returns pre-queued results in FIFO order."""

    def __init__(self, *results: MagicMock) -> None:
        self._queue: list[MagicMock] = list(results)
        self.added: list[Any] = []
        self.flushed: bool = False

    async def execute(self, _stmt: Any) -> MagicMock:
        return self._queue.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# _derive_slug unit tests
# ---------------------------------------------------------------------------


class TestDeriveSlug:
    def test_lowercases_and_replaces_spaces(self) -> None:
        assert _derive_slug("Pebble Beach GC") == "pebble-beach-gc"

    def test_collapses_special_chars_to_hyphens(self) -> None:
        assert _derive_slug("Club & Resort!") == "club-resort"

    def test_strips_leading_trailing_hyphens(self) -> None:
        assert _derive_slug("  !!Club!!  ") == "club"

    def test_truncates_at_100_chars(self) -> None:
        assert len(_derive_slug("a" * 200)) == 100

    def test_digits_preserved(self) -> None:
        assert _derive_slug("Club 19th Hole") == "club-19th-hole"


# ---------------------------------------------------------------------------
# ClubProvisioningService unit tests
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    """Run a coroutine synchronously — avoids pytest-asyncio dependency."""
    return asyncio.run(coro)


class TestClubProvisioningService:

    def test_provision_creates_club_and_draft_pool(self) -> None:
        club = _make_club()
        db = _QueueDB(
            _make_result(scalar=_make_session()),       # _load_session
            _make_result(scalar=_make_claim()),         # _load_claim
            _make_result(scalar=_make_user()),          # _load_owner
            _make_result(rowcount=1),                   # pg_insert(Club) — new row
            _make_result(scalar_one=club),              # select(Club) by slug
        )

        result = _run(ClubProvisioningService().provision(db, "claim_abc"))

        assert result is club
        assert db.flushed is True
        pools = [o for o in db.added if isinstance(o, GolfPool)]
        assert len(pools) == 1
        assert pools[0].status == "draft"
        assert pools[0].club_id == club.id
        assert "pebble-beach-gc" in pools[0].code

    def test_provision_noop_returns_existing_club(self) -> None:
        """ON CONFLICT DO NOTHING path: no pool created, existing club returned."""
        club = _make_club()
        db = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=_make_claim()),
            _make_result(scalar=_make_user()),
            _make_result(rowcount=0),                   # conflict — no insert
            _make_result(scalar_one=club),
        )

        result = _run(ClubProvisioningService().provision(db, "claim_abc"))

        assert result is club
        assert db.flushed is False
        assert not [o for o in db.added if isinstance(o, GolfPool)]

    def test_provision_no_owner_when_user_missing(self) -> None:
        """Provisioning succeeds even when the owner user row doesn't exist yet."""
        club = _make_club(owner_user_id=None)
        db = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=_make_claim()),
            _make_result(scalar=None),                  # user not found
            _make_result(rowcount=1),
            _make_result(scalar_one=club),
        )

        result = _run(ClubProvisioningService().provision(db, "claim_abc"))
        assert result.owner_user_id is None

    def test_provision_raises_when_no_session(self) -> None:
        db = _QueueDB(_make_result(scalar=None))
        try:
            _run(ClubProvisioningService().provision(db, "claim_abc"))
            assert False, "expected ProvisioningError"
        except ProvisioningError as exc:
            assert "No onboarding session" in str(exc)

    def test_provision_raises_when_session_not_claimed_pending(self) -> None:
        db = _QueueDB(_make_result(scalar=_make_session(status="pending")))
        try:
            _run(ClubProvisioningService().provision(db, "claim_abc"))
            assert False, "expected ProvisioningError"
        except ProvisioningError as exc:
            assert "not in claimed status" in str(exc)

    def test_provision_raises_when_session_not_claimed_paid(self) -> None:
        db = _QueueDB(_make_result(scalar=_make_session(status="paid")))
        try:
            _run(ClubProvisioningService().provision(db, "claim_abc"))
            assert False, "expected ProvisioningError"
        except ProvisioningError as exc:
            assert "not in claimed status" in str(exc)

    def test_provision_raises_when_session_expired(self) -> None:
        db = _QueueDB(_make_result(scalar=_make_session(status="expired")))
        try:
            _run(ClubProvisioningService().provision(db, "claim_abc"))
            assert False, "expected ProvisioningError"
        except ProvisioningError as exc:
            assert "not in claimed status" in str(exc)

    def test_provision_raises_when_claim_missing(self) -> None:
        db = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=None),                  # claim not found
        )
        try:
            _run(ClubProvisioningService().provision(db, "claim_abc"))
            assert False, "expected ProvisioningError"
        except ProvisioningError as exc:
            assert "No club claim" in str(exc)

    def test_concurrent_provisioning_one_pool_created(self) -> None:
        """Simulate two concurrent callers via asyncio.gather: exactly one pool created.

        This mirrors PostgreSQL ON CONFLICT DO NOTHING behaviour under concurrent load:
        - db1 wins the race (rowcount=1) → creates draft GolfPool
        - db2 loses the race (rowcount=0) → returns existing Club, no pool
        Both resolve to the same slug; exactly one pool exists across both sessions.
        """
        club = _make_club()

        db1 = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=_make_claim()),
            _make_result(scalar=_make_user()),
            _make_result(rowcount=1),                   # insert wins
            _make_result(scalar_one=club),
        )
        db2 = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=_make_claim()),
            _make_result(scalar=_make_user()),
            _make_result(rowcount=0),                   # conflict — no-op
            _make_result(scalar_one=club),
        )

        svc = ClubProvisioningService()

        async def _run_concurrent() -> tuple[Club, Club]:
            return await asyncio.gather(
                svc.provision(db1, "claim_abc"),
                svc.provision(db2, "claim_abc"),
            )

        club1, club2 = _run(_run_concurrent())

        assert club1.slug == club2.slug
        all_pools = [o for o in db1.added + db2.added if isinstance(o, GolfPool)]
        assert len(all_pools) == 1  # exactly one pool across both callers


# ---------------------------------------------------------------------------
# Endpoint tests — POST /clubs/{claim_id}/provision
# ---------------------------------------------------------------------------


def _make_app(db: _QueueDB) -> TestClient:
    async def _override() -> Any:
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override
    app.include_router(router)
    return TestClient(app)


class TestProvisionEndpoint:

    def test_200_provisions_new_club(self) -> None:
        club = _make_club()
        db = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=_make_claim()),
            _make_result(scalar=_make_user()),
            _make_result(rowcount=1),
            _make_result(scalar_one=club),
        )
        client = _make_app(db)

        resp = client.post("/clubs/claim_abc/provision")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["clubId"] == club.club_id
        assert body["slug"] == club.slug
        assert body["status"] == "active"
        assert body["ownerUserId"] == 42

    def test_200_idempotent_returns_existing_club(self) -> None:
        club = _make_club()
        db = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=_make_claim()),
            _make_result(scalar=_make_user()),
            _make_result(rowcount=0),                   # already provisioned
            _make_result(scalar_one=club),
        )
        client = _make_app(db)

        resp = client.post("/clubs/claim_abc/provision")

        assert resp.status_code == 200
        assert resp.json()["slug"] == club.slug

    def test_400_when_no_session_found(self) -> None:
        db = _QueueDB(_make_result(scalar=None))
        client = _make_app(db)

        resp = client.post("/clubs/claim_abc/provision")

        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "provisioning_failed"

    def test_400_when_session_not_claimed(self) -> None:
        db = _QueueDB(_make_result(scalar=_make_session(status="paid")))
        client = _make_app(db)

        resp = client.post("/clubs/claim_abc/provision")

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["error"] == "provisioning_failed"
        assert "claimed" in detail["message"]

    def test_400_when_claim_missing(self) -> None:
        db = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=None),
        )
        client = _make_app(db)

        resp = client.post("/clubs/claim_abc/provision")

        assert resp.status_code == 400

    def test_response_uses_camel_case_keys(self) -> None:
        club = _make_club()
        db = _QueueDB(
            _make_result(scalar=_make_session()),
            _make_result(scalar=_make_claim()),
            _make_result(scalar=_make_user()),
            _make_result(rowcount=1),
            _make_result(scalar_one=club),
        )
        client = _make_app(db)

        resp = client.post("/clubs/claim_abc/provision")

        assert resp.status_code == 200
        body = resp.json()
        # camelCase aliases must be present
        assert "clubId" in body
        assert "ownerUserId" in body
        assert "planId" in body
