"""Backfill embedded tweets for game flows missing social data.

When the pipeline and social scraping run concurrently, VALIDATE_BLOCKS
may find zero in_game tweets, leaving all blocks with
embedded_social_post_id = NULL. This module retroactively attaches
tweets once they become available.

Two entry points:
1. backfill_embedded_tweets_for_game() — single game, called from
   final_whistle_tasks after social scrape completes
2. find_and_backfill_all() — bulk scan, called from the daily sweep
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import attributes, selectinload

from ...db import AsyncSession
from ...db.flow import SportsGameFlow
from ...db.sports import SportsGame
from .stages.embedded_tweets import load_and_attach_embedded_tweets, validate_embedded_tweet_ids

logger = logging.getLogger(__name__)

# See docs/gameflow/version-semantics.md.
FLOW_VERSION = "v2-blocks"


async def backfill_embedded_tweets_for_game(
    session: AsyncSession,
    game_id: int,
    *,
    flow: SportsGameFlow | None = None,
) -> dict[str, Any]:
    """Backfill embedded tweets for a single game's flow.

    Eligibility: flow exists, all blocks have embedded_social_post_id is None,
    and in_game tweets are now available.

    Uses the shared load_and_attach_embedded_tweets SSOT function
    (same logic as the pipeline path in validate_blocks).

    Args:
        session: Async database session.
        game_id: ID of the game to backfill.
        flow: Pre-loaded flow object. When called from the bulk path the
            caller already has the row, so passing it avoids a redundant query.

    Returns:
        Dict with status and details of the backfill operation.
    """
    if flow is None:
        flow_result = await session.execute(
            select(SportsGameFlow).where(
                SportsGameFlow.game_id == game_id,
                SportsGameFlow.story_version == FLOW_VERSION,
            )
        )
        flow = flow_result.scalar_one_or_none()

    if not flow:
        logger.debug("backfill_embedded_tweets_no_flow", extra={"game_id": game_id})
        return {"game_id": game_id, "status": "no_flow"}

    blocks = flow.blocks_json
    if not blocks:
        logger.debug("backfill_embedded_tweets_no_blocks", extra={"game_id": game_id})
        return {"game_id": game_id, "status": "no_blocks"}

    # Check eligibility: ALL blocks must have embedded_social_post_id is None
    has_any_tweet = any(
        b.get("embedded_social_post_id") is not None for b in blocks
    )
    if has_any_tweet:
        logger.debug(
            "backfill_embedded_tweets_already_has_tweets",
            extra={"game_id": game_id},
        )
        return {"game_id": game_id, "status": "already_has_tweets"}

    # Resolve league_code from the game's league relationship
    game_result = await session.execute(
        select(SportsGame)
        .options(selectinload(SportsGame.league))
        .where(SportsGame.id == game_id)
    )
    game = game_result.scalar_one_or_none()
    if not game:
        return {"game_id": game_id, "status": "game_not_found"}

    league_code = game.league.code if game.league else "NBA"

    # Delegate to shared SSOT function
    updated_blocks, selection = await load_and_attach_embedded_tweets(
        session, game_id, blocks, league_code=league_code
    )

    if not selection:
        logger.debug("backfill_embedded_tweets_no_social", extra={"game_id": game_id})
        return {"game_id": game_id, "status": "no_social_posts"}

    assigned_count = sum(
        1 for b in updated_blocks if b.get("embedded_social_post_id")
    )

    if assigned_count == 0:
        logger.info(
            "backfill_embedded_tweets_none_assigned",
            extra={"game_id": game_id, "candidates": selection.total_candidates},
        )
        return {
            "game_id": game_id,
            "status": "no_tweets_assigned",
            "candidates": selection.total_candidates,
        }

    # Validate all embedded tweet references exist before writing.
    updated_blocks = await validate_embedded_tweet_ids(session, updated_blocks, game_id)

    # Persist updated blocks
    flow.blocks_json = updated_blocks
    attributes.flag_modified(flow, "blocks_json")

    logger.info(
        "backfill_embedded_tweets_success",
        extra={
            "game_id": game_id,
            "flow_id": flow.id,
            "assigned": assigned_count,
            "candidates": selection.total_candidates,
        },
    )

    return {
        "game_id": game_id,
        "status": "backfilled",
        "flow_id": flow.id,
        "tweets_assigned": assigned_count,
        "candidates": selection.total_candidates,
    }


async def find_and_backfill_all(
    session: AsyncSession,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Scan recent flows and backfill any with all-NULL embedded tweets.

    Args:
        session: Async database session.
        lookback_days: How many days back to scan.

    Returns:
        Aggregate results dict.
    """
    from ...utils.datetime_utils import now_utc

    cutoff = now_utc() - timedelta(days=lookback_days)

    flow_result = await session.execute(
        select(SportsGameFlow).where(
            SportsGameFlow.story_version == FLOW_VERSION,
            SportsGameFlow.blocks_json.isnot(None),
            SportsGameFlow.generated_at >= cutoff,
        )
    )
    flows = flow_result.scalars().all()

    results: list[dict[str, Any]] = []
    total_backfilled = 0

    for flow in flows:
        result = await backfill_embedded_tweets_for_game(session, flow.game_id, flow=flow)
        results.append(result)
        if result.get("status") == "backfilled":
            total_backfilled += 1

    logger.info(
        "backfill_embedded_tweets_bulk_complete",
        extra={
            "checked": len(flows),
            "backfilled": total_backfilled,
            "lookback_days": lookback_days,
        },
    )

    return {
        "total_checked": len(flows),
        "total_backfilled": total_backfilled,
        "results": results,
    }
