"""Club provisioning service — idempotent Club + draft GolfPool creation."""

from __future__ import annotations

import asyncio
import logging
import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.audit as audit
from app.db.club import Club
from app.db.golf_pools import GolfPool
from app.db.onboarding import ClubClaim, OnboardingSession
from app.db.users import User
from app.services.email import send_welcome_email

logger = logging.getLogger(__name__)


def _derive_slug(name: str) -> str:
    """Convert a club name to a URL-safe, lowercase, hyphen-separated slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:100]


class ProvisioningError(Exception):
    """Raised when provisioning prerequisites are not met."""


class ClubProvisioningService:
    """Idempotent provisioning of a Club and its initial draft GolfPool.

    Triggered when an OnboardingSession reaches 'claimed' status.  Subsequent
    calls for the same claim_id are no-ops — the existing Club is returned.
    Concurrent callers for the same slug serialize at the DB unique constraint:
    exactly one INSERT lands; others are silently skipped via ON CONFLICT DO NOTHING.
    """

    async def provision(self, db: AsyncSession, claim_id: str) -> Club:
        """Provision a Club (and draft GolfPool) for *claim_id* in one transaction.

        Idempotent and concurrent-safe: duplicate or racing calls for the same
        claim return the existing Club without creating additional rows.

        Raises:
            ProvisioningError: if no session exists for claim_id, the session is
                not in 'claimed' status, or the associated club claim is missing.
        """
        session = await self._load_session(db, claim_id)
        club_claim = await self._load_claim(db, claim_id)
        owner = await self._load_owner(db, club_claim.contact_email)

        slug = _derive_slug(club_claim.club_name)

        # INSERT … ON CONFLICT (slug) DO NOTHING — idempotent anchor.
        # Concurrent callers: the one whose INSERT wins creates the pool;
        # the others see rowcount=0 and return the already-existing Club.
        insert_stmt = (
            pg_insert(Club)
            .values(
                club_id=str(uuid4()),
                slug=slug,
                name=club_claim.club_name,
                plan_id=session.plan_id,
                status="active",
                owner_user_id=owner.id if owner else None,
            )
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        result = await db.execute(insert_stmt)
        is_new = bool(result.rowcount)

        club_result = await db.execute(select(Club).where(Club.slug == slug))
        club = club_result.scalar_one()

        if is_new:
            pool = GolfPool(
                code=f"draft-{slug}",
                name=f"{club_claim.club_name} Pool",
                club_code=slug,
                club_id=club.id,
                status="draft",
            )
            db.add(pool)
            await db.flush()
            logger.info(
                "club_provisioned",
                extra={"club_id": club.club_id, "slug": slug, "claim_id": claim_id},
            )
            audit.emit(
                "club_provisioned",
                actor_type="system",
                actor_id=claim_id,
                club_id=club.id,
                resource_type="club",
                resource_id=club.club_id,
                payload={"slug": slug, "plan_id": session.plan_id},
            )
            asyncio.create_task(
                send_welcome_email(
                    to=club_claim.contact_email,
                    club_name=club_claim.club_name,
                    slug=slug,
                )
            )
        else:
            logger.info(
                "club_provision_noop",
                extra={"slug": slug, "claim_id": claim_id},
            )

        return club

    async def _load_session(self, db: AsyncSession, claim_id: str) -> OnboardingSession:
        result = await db.execute(
            select(OnboardingSession).where(OnboardingSession.claim_id == claim_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise ProvisioningError(
                f"No onboarding session found for claim_id={claim_id!r}"
            )
        if session.status != "claimed":
            raise ProvisioningError(
                f"Session for claim_id={claim_id!r} is not in claimed status"
                f" (current: {session.status!r})"
            )
        return session

    async def _load_claim(self, db: AsyncSession, claim_id: str) -> ClubClaim:
        result = await db.execute(
            select(ClubClaim).where(ClubClaim.claim_id == claim_id)
        )
        claim = result.scalar_one_or_none()
        if claim is None:
            raise ProvisioningError(
                f"No club claim found for claim_id={claim_id!r}"
            )
        return claim

    async def _load_owner(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()
