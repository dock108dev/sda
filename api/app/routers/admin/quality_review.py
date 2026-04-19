"""Admin quality review queue endpoints (ISSUE-051).

GET  /api/admin/quality-review              — paginated pending flows
POST /api/admin/quality-review/{id}/approve — mark reviewed, audit log
POST /api/admin/quality-review/{id}/reject  — delete flow + re-queue
POST /api/admin/quality-review/{id}/regenerate — clear LLM cache + re-queue

All endpoints require admin role (enforced at router registration in main.py).
"""

from __future__ import annotations

import ast
import logging
from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.flow import SportsGameFlow, SportsGameTimelineArtifact
from app.db.quality_review import QualityReviewAction, QualityReviewQueue
from app.db.sports import SportsGame

logger = logging.getLogger(__name__)

router = APIRouter()

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)

# ── Response models ────────────────────────────────────────────────────────────


class QueueItem(BaseModel):
    model_config = _ALIAS_CFG

    id: int
    flow_id: int
    game_id: int
    sport: str
    game_date: datetime | None
    flow_source: str | None
    combined_score: float
    tier1_score: float
    tier2_score: float | None
    tier_breakdown: dict
    forbidden_phrases: list[str]
    narrative_preview: str
    status: str
    created_at: datetime


class QueueListResponse(BaseModel):
    model_config = _ALIAS_CFG

    total: int
    page: int
    page_size: int
    items: list[QueueItem]


class ActionResponse(BaseModel):
    model_config = _ALIAS_CFG

    id: int
    action: str
    ok: bool


# ── Helpers ────────────────────────────────────────────────────────────────────


def _extract_forbidden_phrases(tier_breakdown: dict) -> list[str]:
    """Pull forbidden-phrase list from the tier1 failures stored at escalation."""
    failures: list = tier_breakdown.get("tier1", {}).get("failures", [])
    for f in failures:
        if f.startswith("forbidden_phrases="):
            try:
                return ast.literal_eval(f.split("=", 1)[1])
            except Exception:
                return []
    return []


def _narrative_preview(blocks_json: list | None) -> str:
    if not blocks_json:
        return ""
    return (blocks_json[0].get("narrative", "") or "")[:300]


def _actor(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    return str(uid) if uid else "admin-api-key"


def _get_redis():
    import redis as _redis

    from app.config import settings

    url = getattr(settings, "celery_broker_url", None) or settings.redis_url
    return _redis.from_url(url, decode_responses=True)


def _enqueue_flow_regen(game_id: int) -> None:
    from app.celery_app import celery_app

    celery_app.send_task("trigger_flow_for_game", args=[game_id])


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/quality-review",
    response_model=QueueListResponse,
    summary="Paginated quality review queue",
)
async def list_review_queue(
    status_filter: str = "pending",
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
) -> QueueListResponse:
    """Return paginated flows awaiting human review."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    count_stmt = (
        select(func.count())
        .select_from(QualityReviewQueue)
        .where(QualityReviewQueue.status == status_filter)
    )
    total: int = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(
            QualityReviewQueue,
            SportsGame.game_date,
            SportsGameFlow.flow_source,
            SportsGameFlow.blocks_json,
        )
        .join(SportsGame, QualityReviewQueue.game_id == SportsGame.id)
        .join(SportsGameFlow, QualityReviewQueue.flow_id == SportsGameFlow.id)
        .where(QualityReviewQueue.status == status_filter)
        .order_by(QualityReviewQueue.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await db.execute(stmt)).all()

    items: list[QueueItem] = []
    for row in rows:
        q: QualityReviewQueue = row[0]
        game_date: datetime | None = row[1]
        flow_source: str | None = row[2]
        blocks_json: list | None = row[3]

        items.append(
            QueueItem(
                id=q.id,
                flow_id=q.flow_id,
                game_id=q.game_id,
                sport=q.sport,
                game_date=game_date,
                flow_source=flow_source or "LLM",
                combined_score=q.combined_score,
                tier1_score=q.tier1_score,
                tier2_score=q.tier2_score,
                tier_breakdown=q.tier_breakdown,
                forbidden_phrases=_extract_forbidden_phrases(q.tier_breakdown),
                narrative_preview=_narrative_preview(blocks_json),
                status=q.status,
                created_at=q.created_at,
            )
        )

    return QueueListResponse(total=total, page=page, page_size=page_size, items=items)


@router.post(
    "/quality-review/{queue_id}/approve",
    response_model=ActionResponse,
    summary="Approve a reviewed flow",
)
async def approve_flow(
    queue_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Mark flow as reviewed and log the action."""
    q = await db.get(QualityReviewQueue, queue_id)
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue item not found")

    actor = _actor(request)
    flow_id = q.flow_id

    q.status = "reviewed"
    db.add(
        QualityReviewAction(
            queue_id=queue_id,
            flow_id=flow_id,
            action="approve",
            actor=actor,
        )
    )
    await db.flush()

    logger.info(
        "quality_review_approve",
        extra={"queue_id": queue_id, "flow_id": flow_id, "actor": actor},
    )
    return ActionResponse(id=queue_id, action="approve", ok=True)


@router.post(
    "/quality-review/{queue_id}/reject",
    response_model=ActionResponse,
    summary="Reject flow and enqueue regeneration",
)
async def reject_flow(
    queue_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Delete the flow record and enqueue a fresh generation run."""
    q = await db.get(QualityReviewQueue, queue_id)
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue item not found")

    actor = _actor(request)
    flow_id = q.flow_id
    game_id = q.game_id

    # Audit before deletion (cascade will remove the queue row)
    db.add(
        QualityReviewAction(
            queue_id=queue_id,
            flow_id=flow_id,
            action="reject",
            actor=actor,
        )
    )
    await db.flush()

    # Delete timeline artifact so trigger_flow_for_game does not skip the game
    await db.execute(
        delete(SportsGameTimelineArtifact).where(
            SportsGameTimelineArtifact.game_id == game_id
        )
    )
    # Deleting the flow cascades to quality_review_queue
    flow = await db.get(SportsGameFlow, flow_id)
    if flow is not None:
        await db.delete(flow)
    await db.flush()

    # Enqueue regeneration (fire-and-forget via Celery)
    try:
        _enqueue_flow_regen(game_id)
    except Exception:
        logger.warning(
            "quality_review_reject_enqueue_failed",
            exc_info=True,
            extra={"game_id": game_id, "flow_id": flow_id},
        )

    logger.info(
        "quality_review_reject",
        extra={"queue_id": queue_id, "flow_id": flow_id, "game_id": game_id, "actor": actor},
    )
    return ActionResponse(id=queue_id, action="reject", ok=True)


@router.post(
    "/quality-review/{queue_id}/regenerate",
    response_model=ActionResponse,
    summary="Force LLM re-run ignoring grader cache",
)
async def regenerate_flow(
    queue_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """Clear tier-2 grader cache, delete flow, and enqueue fresh generation."""
    q = await db.get(QualityReviewQueue, queue_id)
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue item not found")

    actor = _actor(request)
    flow_id = q.flow_id
    game_id = q.game_id

    # Clear Redis tier-2 grader cache for this flow so re-grading uses a fresh LLM call
    try:
        redis = _get_redis()
        pattern = f"grader:t2:{flow_id}:*"
        cursor = 0
        while True:
            cursor, keys = redis.scan(cursor, match=pattern, count=100)
            if keys:
                redis.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        logger.warning(
            "quality_review_regenerate_cache_clear_failed",
            exc_info=True,
            extra={"flow_id": flow_id},
        )

    # Audit before deletion
    db.add(
        QualityReviewAction(
            queue_id=queue_id,
            flow_id=flow_id,
            action="regenerate",
            actor=actor,
        )
    )
    await db.flush()

    await db.execute(
        delete(SportsGameTimelineArtifact).where(
            SportsGameTimelineArtifact.game_id == game_id
        )
    )
    flow = await db.get(SportsGameFlow, flow_id)
    if flow is not None:
        await db.delete(flow)
    await db.flush()

    try:
        _enqueue_flow_regen(game_id)
    except Exception:
        logger.warning(
            "quality_review_regenerate_enqueue_failed",
            exc_info=True,
            extra={"game_id": game_id, "flow_id": flow_id},
        )

    logger.info(
        "quality_review_regenerate",
        extra={"queue_id": queue_id, "flow_id": flow_id, "game_id": game_id, "actor": actor},
    )
    return ActionResponse(id=queue_id, action="regenerate", ok=True)
