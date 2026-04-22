"""Centralized plan limit enforcement for club entitlements.

All plan limits live here — no scattered checks in routers or services.
EntitlementError is raised on any violation; the global FastAPI handler
converts it to HTTP 403 with code ENTITLEMENT_EXCEEDED.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.club import Club
from app.db.golf_pools import GolfPool, GolfPoolEntry


class AppError(Exception):
    """Base class for domain errors that map to specific HTTP responses."""


class EntitlementError(AppError):
    """Raised when a club's plan limit is exceeded or a feature is not available."""


class SeatLimitError(AppError):
    """Raised when a club's admin seat limit is exceeded; maps to HTTP 402."""


class SubscriptionPastDueError(AppError):
    """Raised when a club's subscription is past_due; maps to HTTP 402."""


@dataclass(frozen=True)
class PlanLimits:
    max_pools_active: int | None  # None = unlimited
    max_entries_per_pool: int | None  # None = unlimited
    max_admins_per_club: int | None  # None = unlimited
    scoring_enabled: bool
    branding_enabled: bool
    custom_branding: bool


# Single source of truth for per-plan limits.
PLAN_LIMITS: dict[str, PlanLimits] = {
    "price_starter": PlanLimits(
        max_pools_active=1,
        max_entries_per_pool=50,
        max_admins_per_club=1,
        scoring_enabled=False,
        branding_enabled=False,
        custom_branding=False,
    ),
    "price_pro": PlanLimits(
        max_pools_active=5,
        max_entries_per_pool=200,
        max_admins_per_club=3,
        scoring_enabled=True,
        branding_enabled=False,
        custom_branding=False,
    ),
    "price_enterprise": PlanLimits(
        max_pools_active=None,
        max_entries_per_pool=None,
        max_admins_per_club=None,
        scoring_enabled=True,
        branding_enabled=True,
        custom_branding=True,
    ),
}

_DEFAULT_PLAN = PlanLimits(
    max_pools_active=1,
    max_entries_per_pool=50,
    max_admins_per_club=1,
    scoring_enabled=False,
    branding_enabled=False,
    custom_branding=False,
)

# Pool statuses that count against the active-pool plan limit.
_ACTIVE_STATUSES = ("open", "locked", "live")

# Boolean feature flags that can be checked via assert_feature / check_feature.
_FEATURES = frozenset({"scoring_enabled", "branding_enabled", "custom_branding"})


class EntitlementService:
    """Enforces per-plan limits. All check methods raise EntitlementError on violation."""

    async def check_subscription_active(self, club_id: int, db: AsyncSession) -> None:
        """Raise SubscriptionPastDueError if the club's subscription is past_due.

        Clubs without a Stripe customer record are treated as free-tier (no block).
        """
        from app.db.stripe import StripeSubscription

        result = await db.execute(select(Club).where(Club.id == club_id))
        club = result.scalar_one_or_none()
        if club is None or not club.stripe_customer_id:
            return
        sub_result = await db.execute(
            select(StripeSubscription)
            .where(StripeSubscription.stripe_customer_id == club.stripe_customer_id)
            .order_by(StripeSubscription.id.desc())
            .limit(1)
        )
        sub = sub_result.scalar_one_or_none()
        if sub and sub.status == "past_due":
            raise SubscriptionPastDueError(
                "Payment past due — update your payment method to create new pools"
            )

    async def _get_limits(self, club_id: int, db: AsyncSession) -> PlanLimits:
        result = await db.execute(select(Club).where(Club.id == club_id))
        club = result.scalar_one_or_none()
        if club is None:
            raise EntitlementError(f"Club {club_id} not found")
        return PLAN_LIMITS.get(club.plan_id, _DEFAULT_PLAN)

    async def check_pool_limit(self, club_id: int, db: AsyncSession) -> None:
        """Raise SubscriptionPastDueError (402) or EntitlementError (403) on pool creation block."""
        await self.check_subscription_active(club_id, db)
        limits = await self._get_limits(club_id, db)
        if limits.max_pools_active is None:
            return
        result = await db.execute(
            select(func.count(GolfPool.id)).where(
                GolfPool.club_id == club_id,
                GolfPool.status.in_(_ACTIVE_STATUSES),
            )
        )
        count = result.scalar() or 0
        if count >= limits.max_pools_active:
            raise EntitlementError(
                f"Plan limit reached: maximum {limits.max_pools_active} active pools allowed"
            )

    async def check_entry_limit(
        self, club_id: int, pool_id: int, db: AsyncSession
    ) -> None:
        """Raise EntitlementError if the pool has reached its per-pool entry limit."""
        limits = await self._get_limits(club_id, db)
        if limits.max_entries_per_pool is None:
            return
        result = await db.execute(
            select(func.count(GolfPoolEntry.id)).where(
                GolfPoolEntry.pool_id == pool_id,
            )
        )
        count = result.scalar() or 0
        if count >= limits.max_entries_per_pool:
            raise EntitlementError(
                f"Plan limit reached: maximum {limits.max_entries_per_pool} entries per pool allowed"
            )

    async def check_admin_seat(self, club_id: int, db: AsyncSession) -> None:
        """Raise SeatLimitError if the club has reached its admin seat limit.

        Counts existing owner + admin memberships. Viewers are excluded.
        """
        from app.db.club_membership import ClubMembership

        limits = await self._get_limits(club_id, db)
        if limits.max_admins_per_club is None:
            return
        result = await db.execute(
            select(func.count(ClubMembership.id)).where(
                ClubMembership.club_id == club_id,
                ClubMembership.role.in_(("owner", "admin")),
            )
        )
        count = result.scalar() or 0
        if count >= limits.max_admins_per_club:
            raise SeatLimitError(
                f"Plan limit reached: maximum {limits.max_admins_per_club} admin seats allowed"
            )

    async def assert_feature(
        self, club_id: int, feature: str, db: AsyncSession
    ) -> None:
        """Raise EntitlementError if the club's plan does not include the named feature.

        Valid features: scoring_enabled, branding_enabled, custom_branding.
        """
        if feature not in _FEATURES:
            raise EntitlementError(f"Unknown feature: {feature!r}")
        limits = await self._get_limits(club_id, db)
        if not getattr(limits, feature):
            raise EntitlementError(
                f"Feature {feature!r} is not available on your current plan"
            )

    async def check_feature(
        self, club_id: int, feature: str, db: AsyncSession
    ) -> None:
        """Alias for assert_feature — raises EntitlementError on plan violation."""
        await self.assert_feature(club_id, feature, db)
