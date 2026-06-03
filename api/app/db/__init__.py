"""Database models and session management.

Import models from their respective modules:
    from app.db.sports import SportsGame, SportsTeam
    from app.db.pipeline import GamePipelineRun
    from app.services.pipeline.models import PipelineStage  # canonical definition

Session management:
    from app.db import AsyncSession, get_db
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from . import flow as _flow  # noqa: F401 — register relationship targets
from . import hooks as _hooks  # noqa: F401 — registers ORM event listeners
from . import mlb_advanced as _mlb_advanced  # noqa: F401 — register relationship targets
from . import nba_advanced as _nba_advanced  # noqa: F401 — register relationship targets
from . import ncaab_advanced as _ncaab_advanced  # noqa: F401 — register relationship targets
from . import nfl_advanced as _nfl_advanced  # noqa: F401 — register relationship targets
from . import nhl_advanced as _nhl_advanced  # noqa: F401 — register relationship targets
from . import odds as _odds  # noqa: F401 — register relationship targets
from . import scraper as _scraper  # noqa: F401 — register relationship targets
from . import social as _social  # noqa: F401 — register relationship targets
from . import telemetry as _telemetry  # noqa: F401 — registers CircuitBreakerTripEvent mapper
from .audit import AuditEvent  # noqa: F401 — register ORM model for Alembic autogenerate
from .base import Base
from .club import Club  # noqa: F401 — register ORM model for Alembic autogenerate
from .golf_pools import (
    PoolLifecycleEvent,  # noqa: F401 — register ORM model for Alembic autogenerate
)
from .magic_link import MagicLinkToken  # noqa: F401 — register ORM model for Alembic autogenerate
from .onboarding import (  # noqa: F401 — register ORM models for Alembic autogenerate
    ClubClaim,
    OnboardingSession,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Lazy-loaded engine and session factory to avoid initialization at import time.
# This allows tests to import modules without triggering database connection,
# and lets the scraper import ORM models without pulling in the API config.
_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    """Get or create the database engine (lazy initialization)."""
    global _engine
    if _engine is None:
        from ..config import settings
        from ..otel import instrument_sqlalchemy_engine

        _engine = create_async_engine(settings.database_url, echo=settings.sql_echo, future=True)
        instrument_sqlalchemy_engine(_engine)
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the session factory (lazy initialization)."""
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency for database sessions with commit/rollback semantics."""
    session_factory = _get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                logger.warning("session_rollback_failed", exc_info=True)
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_async_session():
    """Context manager for ad-hoc scripts."""
    session_factory = _get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                logger.warning("session_rollback_failed", exc_info=True)
            raise


async def close_db() -> None:
    """Close the database connection."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


__all__ = [
    "Base",
    "AsyncSession",
    "AuditEvent",
    "Club",
    "ClubClaim",
    "MagicLinkToken",
    "OnboardingSession",
    "PoolLifecycleEvent",
    "get_db",
    "get_async_session",
    "close_db",
]
