"""
Database helpers for the scraper service.

This module provides synchronous database session management for Celery tasks.
It reuses the ORM models from the sports-data-admin API to maintain consistency
across services and avoid duplicate model definitions.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .logging import logger

# Ensure the sports-data-admin API package is importable so we can reuse ORM models
# This avoids duplicating model definitions and ensures schema consistency
# Insert at the beginning to ensure our app package takes precedence
SPORTS_API_PATH = Path(__file__).resolve().parents[2] / "api"
if str(SPORTS_API_PATH) not in sys.path:
    sys.path.insert(0, str(SPORTS_API_PATH))

try:
    # Import all models from the new modular structure
    from app.db.cache import OpenAIResponseCache  # type: ignore
    from app.db.config import (  # type: ignore
        GameReadingPosition,
    )
    from app.db.flow import (  # type: ignore
        SportsGameFlow,
        SportsGameTimelineArtifact,
    )
    from app.db.mlb_advanced import (  # type: ignore
        MLBGameAdvancedStats,
        MLBPitcherGameStats,
        MLBPlayerAdvancedStats,
        MLBPlayerFieldingStats,
    )
    from app.db.nba_advanced import NBAGameAdvancedStats, NBAPlayerAdvancedStats  # type: ignore
    from app.db.ncaab_advanced import (  # type: ignore
        NCAABGameAdvancedStats,
        NCAABPlayerAdvancedStats,
    )
    from app.db.nfl_advanced import NFLGameAdvancedStats, NFLPlayerAdvancedStats  # type: ignore
    from app.db.nhl_advanced import (  # type: ignore
        NHLGameAdvancedStats,
        NHLGoalieAdvancedStats,
        NHLSkaterAdvancedStats,
    )
    from app.db.odds import (  # type: ignore
        ClosingLine,
        FairbetGameOddsWork,
        SportsGameOdds,
    )
    from app.db.pipeline import (  # type: ignore
        BulkFlowGenerationJob,
        BulkFlowJobStatus,
        GamePipelineRun,
        GamePipelineStage,
        PipelineRunStatus,
        PipelineStage,
        PipelineStageStatus,
        PipelineTrigger,
    )
    from app.db.resolution import (  # type: ignore
        EntityResolution,
        PBPSnapshot,
        PBPSnapshotType,
        ResolutionStatus,
    )
    from app.db.scraper import (  # type: ignore
        SportsGameConflict,
        SportsJobRun,
        SportsMissingPbp,
        SportsScrapeRun,
    )
    from app.db.social import (  # type: ignore
        MappingStatus,
        SocialAccountPoll,
        TeamSocialAccount,
        TeamSocialPost,
    )
    from app.db.sports import (  # type: ignore
        GameStatus,
        SportsGame,
        SportsGamePlay,
        SportsLeague,
        SportsPlayer,
        SportsPlayerBoxscore,
        SportsTeam,
        SportsTeamBoxscore,
    )

    # Unified namespace exposing all ORM models for scraper imports
    db_models = SimpleNamespace(
        # Enums
        GameStatus=GameStatus,
        MappingStatus=MappingStatus,
        PBPSnapshotType=PBPSnapshotType,
        ResolutionStatus=ResolutionStatus,
        PipelineStage=PipelineStage,
        PipelineRunStatus=PipelineRunStatus,
        PipelineStageStatus=PipelineStageStatus,
        PipelineTrigger=PipelineTrigger,
        BulkFlowJobStatus=BulkFlowJobStatus,
        # Sports models
        SportsLeague=SportsLeague,
        SportsTeam=SportsTeam,
        SportsPlayer=SportsPlayer,
        SportsGame=SportsGame,
        SportsTeamBoxscore=SportsTeamBoxscore,
        SportsPlayerBoxscore=SportsPlayerBoxscore,
        SportsGamePlay=SportsGamePlay,
        # Pipeline models
        GamePipelineRun=GamePipelineRun,
        GamePipelineStage=GamePipelineStage,
        BulkFlowGenerationJob=BulkFlowGenerationJob,
        # Social models
        TeamSocialPost=TeamSocialPost,
        TeamSocialAccount=TeamSocialAccount,
        SocialAccountPoll=SocialAccountPoll,
        # Flow models
        SportsGameTimelineArtifact=SportsGameTimelineArtifact,
        SportsGameFlow=SportsGameFlow,
        # Scraper models
        SportsScrapeRun=SportsScrapeRun,
        SportsJobRun=SportsJobRun,
        SportsGameConflict=SportsGameConflict,
        SportsMissingPbp=SportsMissingPbp,
        # Resolution models
        PBPSnapshot=PBPSnapshot,
        EntityResolution=EntityResolution,
        # Odds models
        SportsGameOdds=SportsGameOdds,
        FairbetGameOddsWork=FairbetGameOddsWork,
        ClosingLine=ClosingLine,
        # Config models
        GameReadingPosition=GameReadingPosition,
        # Cache models
        OpenAIResponseCache=OpenAIResponseCache,
        # MLB advanced stats
        MLBGameAdvancedStats=MLBGameAdvancedStats,
        MLBPlayerAdvancedStats=MLBPlayerAdvancedStats,
        MLBPitcherGameStats=MLBPitcherGameStats,
        MLBPlayerFieldingStats=MLBPlayerFieldingStats,
        # NBA advanced stats
        NBAGameAdvancedStats=NBAGameAdvancedStats,
        NBAPlayerAdvancedStats=NBAPlayerAdvancedStats,
        # NHL advanced stats
        NHLGameAdvancedStats=NHLGameAdvancedStats,
        NHLSkaterAdvancedStats=NHLSkaterAdvancedStats,
        NHLGoalieAdvancedStats=NHLGoalieAdvancedStats,
        # NFL advanced stats
        NFLGameAdvancedStats=NFLGameAdvancedStats,
        NFLPlayerAdvancedStats=NFLPlayerAdvancedStats,
        # NCAAB advanced stats
        NCAABGameAdvancedStats=NCAABGameAdvancedStats,
        NCAABPlayerAdvancedStats=NCAABPlayerAdvancedStats,
    )
except ImportError as exc:
    raise RuntimeError(
        "Unable to import sports-data-admin api models. "
        "Did you install the API service dependencies?"
    ) from exc


engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,  # Recycle connections after 30 min to avoid stale PG backends
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


@contextmanager
def get_session() -> Iterator[Session]:
    """
    Provide a transactional database session context manager.

    Use this in Celery tasks and other synchronous code paths.
    Automatically handles commit/rollback and session cleanup.

    Usage:
        with get_session() as session:
            # Use session here
            session.add(object)
            # Commit happens automatically on exit
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as exc:  # pragma: no cover
        session.rollback()
        logger.exception("DB session rollback", error=str(exc))
        raise
    finally:
        session.close()


__all__ = ["get_session", "db_models", "engine"]
