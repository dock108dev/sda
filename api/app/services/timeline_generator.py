"""
Timeline artifact generation for finalized games.

Builds PBP, social, and odds events for game timelines:
1. PBP events from game plays (with phase assignment)
2. Social events from posts (with phase and role assignment)
3. Odds events from opening/closing lines and movements
4. Merge events using phase-first ordering
5. Validate timeline structure

Social and odds data are optional — the pipeline works with PBP alone.

Related modules:
- timeline_types.py: Constants, data classes, exceptions
- timeline_phases.py: Phase utilities and timing calculations
- timeline_events.py: PBP event building and timeline merging
- social_events.py: Social post processing and role assignment
- odds_events.py: Odds event processing and movement detection
- timeline_validation.py: Validation and sanity checks

See docs/TIMELINE_ASSEMBLY.md for the assembly contract.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db import AsyncSession
from ..db.flow import SportsGameTimelineArtifact
from ..db.odds import SportsGameOdds
from ..db.social import TeamSocialPost
from ..db.sports import SportsGame, SportsGamePlay
from ..utils.datetime_utils import now_utc
from .odds_events import build_odds_events
from .social_events import build_social_events
from .timeline_events import build_pbp_events, merge_timeline_events
from .timeline_phases import compute_phase_boundaries, nba_game_end
from .timeline_types import (
    DEFAULT_TIMELINE_VERSION,
    SOCIAL_POSTGAME_WINDOW_SECONDS,
    SOCIAL_PREGAME_WINDOW_SECONDS,
    TimelineArtifactPayload,
    TimelineGenerationError,
)
from .timeline_validation import TimelineValidationError, validate_and_log

logger = logging.getLogger(__name__)


async def generate_timeline_artifact(
    session: AsyncSession,
    game_id: int,
    timeline_version: str = DEFAULT_TIMELINE_VERSION,
    generated_by: str = "api",
    generation_reason: str | None = None,
) -> TimelineArtifactPayload:
    """
    Generate and persist a complete timeline artifact for a game.

    This is the main async entry point. It:
    1. Fetches game, plays, and social posts from DB
    2. Builds PBP and social events with phases
    3. Merges into unified timeline
    4. Runs game analysis and summary generation
    5. Validates and persists the artifact
    """
    logger.info(
        "timeline_artifact_generation_started",
        extra={"game_id": game_id, "timeline_version": timeline_version},
    )
    try:
        # Fetch game with relations
        result = await session.execute(
            select(SportsGame)
            .options(
                selectinload(SportsGame.league),
                selectinload(SportsGame.home_team),
                selectinload(SportsGame.away_team),
            )
            .where(SportsGame.id == game_id)
        )
        game = result.scalar_one_or_none()
        if not game:
            raise TimelineGenerationError("Game not found", status_code=404)

        if not game.is_final:
            raise TimelineGenerationError("Game is not final", status_code=409)

        league_code = game.league.code if game.league else "UNK"

        # Fetch plays with team relationship for team_abbreviation
        plays_result = await session.execute(
            select(SportsGamePlay)
            .options(selectinload(SportsGamePlay.team))
            .where(SportsGamePlay.game_id == game_id)
            .order_by(SportsGamePlay.play_index)
        )
        plays = plays_result.scalars().all()
        if not plays:
            raise TimelineGenerationError("Missing play-by-play data", status_code=422)

        game_start = game.game_date
        game_end = nba_game_end(game_start, plays)
        has_overtime = any((play.quarter or 0) > 4 for play in plays)

        # Compute phase boundaries for social event assignment
        phase_boundaries = compute_phase_boundaries(game_start, has_overtime)

        # Use TeamSocialPost (mapped, pregame/in_game only) — postgame never affects flows
        social_window_start = game_start - timedelta(
            seconds=SOCIAL_PREGAME_WINDOW_SECONDS
        )
        social_window_end = game_end + timedelta(
            seconds=SOCIAL_POSTGAME_WINDOW_SECONDS
        )

        posts_result = await session.execute(
            select(TeamSocialPost)
            .where(
                TeamSocialPost.game_id == game_id,
                TeamSocialPost.mapping_status == "mapped",
                TeamSocialPost.game_phase.in_(["pregame", "in_game"]),
                TeamSocialPost.posted_at >= social_window_start,
                TeamSocialPost.posted_at <= social_window_end,
            )
            .order_by(TeamSocialPost.posted_at)
        )
        posts: list[TeamSocialPost] = list(posts_result.scalars().all())

        logger.info(
            "social_posts_window",
            extra={
                "game_id": game_id,
                "window_start": social_window_start.isoformat(),
                "window_end": social_window_end.isoformat(),
                "posts_found": len(posts),
            },
        )

        # Build PBP events
        logger.info(
            "timeline_artifact_phase_started",
            extra={"game_id": game_id, "phase": "build_pbp_events"},
        )
        pbp_events = build_pbp_events(plays, game_start)
        if not pbp_events:
            raise TimelineGenerationError("Missing play-by-play data", status_code=422)
        logger.info(
            "timeline_artifact_phase_completed",
            extra={
                "game_id": game_id,
                "phase": "build_pbp_events",
                "events": len(pbp_events),
            },
        )

        # Build social events with heuristic role classification
        logger.info(
            "timeline_artifact_phase_started",
            extra={"game_id": game_id, "phase": "build_social_events"},
        )
        social_events = build_social_events(
            posts,
            phase_boundaries,
            game_start=game_start,
            league_code=league_code,
            has_overtime=has_overtime,
        )
        logger.info(
            "timeline_artifact_phase_completed",
            extra={
                "game_id": game_id,
                "phase": "build_social_events",
                "social_events": len(social_events),
                "social_posts": len(posts),
            },
        )

        # Build odds events
        logger.info(
            "timeline_artifact_phase_started",
            extra={"game_id": game_id, "phase": "build_odds_events"},
        )
        odds_result = await session.execute(
            select(SportsGameOdds)
            .where(SportsGameOdds.game_id == game_id)
            .order_by(SportsGameOdds.observed_at)
        )
        odds_rows = list(odds_result.scalars().all())
        odds_events = build_odds_events(odds_rows, game_start, phase_boundaries)

        timeline = merge_timeline_events(pbp_events, social_events, odds_events)
        logger.info(
            "timeline_artifact_phase_completed",
            extra={
                "game_id": game_id,
                "phase": "build_odds_events",
                "timeline_events": len(timeline),
                "odds_rows": len(odds_rows),
                "odds_events": len(odds_events),
            },
        )

        # Build summary and analysis metadata
        game_analysis: dict[str, Any] = {"key_moments": [], "game_flow": {}}
        summary_json: dict[str, Any] = {
            "ai_generated": False,
            "summary_text": "",
            "highlights": [],
        }

        # Validation
        logger.info(
            "timeline_artifact_phase_started",
            extra={"game_id": game_id, "phase": "validation"},
        )
        try:
            validation_report = validate_and_log(timeline, summary_json, game_id)
            logger.info(
                "timeline_artifact_phase_completed",
                extra={
                    "game_id": game_id,
                    "phase": "validation",
                    "verdict": validation_report.verdict,
                    "critical_passed": validation_report.critical_passed,
                    "warnings": validation_report.warnings_count,
                },
            )
        except TimelineValidationError as exc:
            logger.error(
                "timeline_artifact_validation_blocked",
                extra={
                    "game_id": game_id,
                    "phase": "validation",
                    "report": exc.report.to_dict(),
                },
            )
            raise TimelineGenerationError(
                f"Timeline validation failed: {exc}",
                status_code=422,
            ) from exc

        # Persist artifact
        logger.info(
            "timeline_artifact_phase_started",
            extra={"game_id": game_id, "phase": "persist_artifact"},
        )
        generated_at = now_utc()
        artifact_result = await session.execute(
            select(SportsGameTimelineArtifact).where(
                SportsGameTimelineArtifact.game_id == game_id,
                SportsGameTimelineArtifact.sport == league_code,
                SportsGameTimelineArtifact.timeline_version
                == timeline_version,
            )
        )
        artifact = artifact_result.scalar_one_or_none()

        if artifact is None:
            artifact = SportsGameTimelineArtifact(
                game_id=game_id,
                sport=league_code,
                timeline_version=timeline_version,
                generated_at=generated_at,
                timeline_json=timeline,
                game_analysis_json=game_analysis,
                summary_json=summary_json,
                generated_by=generated_by,
                generation_reason=generation_reason,
            )
            session.add(artifact)
        else:
            artifact.generated_at = generated_at
            artifact.timeline_json = timeline
            artifact.game_analysis_json = game_analysis
            artifact.summary_json = summary_json
            artifact.generated_by = generated_by
            artifact.generation_reason = generation_reason

        await session.flush()
        logger.info(
            "timeline_artifact_phase_completed",
            extra={"game_id": game_id, "phase": "persist_artifact"},
        )

        logger.info(
            "timeline_artifact_generated",
            extra={
                "game_id": game_id,
                "timeline_version": timeline_version,
                "timeline_events": len(timeline),
                "social_posts": len(posts),
                "odds_events": len(odds_events),
                "plays": len(plays),
            },
        )

        return TimelineArtifactPayload(
            game_id=game_id,
            sport=league_code,
            timeline_version=timeline_version,
            generated_at=generated_at,
            timeline=timeline,
            summary=summary_json,
            game_analysis=game_analysis,
        )
    except Exception:
        logger.exception(
            "timeline_artifact_generation_failed",
            extra={"game_id": game_id, "timeline_version": timeline_version},
        )
        raise
