#!/usr/bin/env python3
"""
Backfill timeline artifacts for NBA final games.

Usage:
    python -m scripts.backfill_timelines [--limit N] [--dry-run]
"""

import argparse
import asyncio
import logging
import time

from sqlalchemy import text

from app.db import get_async_session
from app.services.timeline_generator import (
    TimelineGenerationError,
    generate_timeline_artifact,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5


async def get_eligible_games(limit: int | None = None) -> list[int]:
    """Get NBA final game IDs that need timeline generation."""
    query = text("""
        SELECT g.id
        FROM sports_games g
        JOIN sports_leagues l ON g.league_id = l.id
        LEFT JOIN sports_game_timeline_artifacts ta ON ta.game_id = g.id
        WHERE l.code = 'NBA'
          AND g.status = 'final'
          AND ta.id IS NULL
          AND EXISTS (SELECT 1 FROM sports_game_plays p WHERE p.game_id = g.id)
        ORDER BY g.game_date DESC
        LIMIT :limit
    """)

    async with get_async_session() as session:
        result = await session.execute(query, {"limit": limit or 10000})
        return [row[0] for row in result.fetchall()]


async def backfill_game(game_id: int) -> dict:
    """Generate timeline for a single game, return stats."""
    start_time = time.time()
    result = {
        "game_id": game_id,
        "success": False,
        "duration_ms": 0,
        "timeline_events": 0,
        "analysis_keys": 0,
        "summary_keys": 0,
        "error": None,
    }

    try:
        async with get_async_session() as session:
            artifact = await generate_timeline_artifact(
                session,
                game_id,
                generated_by="backfill",
                generation_reason="initial_rollout",
            )
            await session.commit()

            result["success"] = True
            result["timeline_events"] = len(artifact.timeline)
            result["analysis_keys"] = len(artifact.game_analysis)
            result["summary_keys"] = len(artifact.summary)

    except TimelineGenerationError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"

    result["duration_ms"] = round((time.time() - start_time) * 1000, 2)
    return result


async def run_backfill(limit: int | None = None, dry_run: bool = False):
    """Run the backfill process."""
    logger.info("=" * 60)
    logger.info("TIMELINE BACKFILL - Phase B")
    logger.info("=" * 60)

    game_ids = await get_eligible_games(limit)
    logger.info(f"Eligible games to process: {len(game_ids)}")

    if dry_run:
        logger.info("DRY RUN - would process these game IDs:")
        for gid in game_ids[:20]:
            logger.info(f"  - {gid}")
        if len(game_ids) > 20:
            logger.info(f"  ... and {len(game_ids) - 20} more")
        return

    stats = {
        "total": len(game_ids),
        "success": 0,
        "failed": 0,
        "consecutive_failures": 0,
        "total_duration_ms": 0,
        "errors": [],
    }

    for i, game_id in enumerate(game_ids, 1):
        result = await backfill_game(game_id)
        stats["total_duration_ms"] += result["duration_ms"]

        if result["success"]:
            stats["success"] += 1
            stats["consecutive_failures"] = 0
            logger.info(
                f"[{i}/{len(game_ids)}] ✅ game_id={game_id} | "
                f"duration={result['duration_ms']}ms | "
                f"timeline={result['timeline_events']} events | "
                f"analysis={result['analysis_keys']} keys | "
                f"summary={result['summary_keys']} keys"
            )
        else:
            stats["failed"] += 1
            stats["consecutive_failures"] += 1
            stats["errors"].append({"game_id": game_id, "error": result["error"]})
            logger.warning(
                f"[{i}/{len(game_ids)}] ❌ game_id={game_id} | "
                f"duration={result['duration_ms']}ms | "
                f"error={result['error']}"
            )

            if stats["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    f"STOPPING: {MAX_CONSECUTIVE_FAILURES} consecutive failures reached"
                )
                break

    # Summary
    logger.info("=" * 60)
    logger.info("BACKFILL COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total processed: {stats['success'] + stats['failed']}")
    logger.info(f"Success: {stats['success']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Total duration: {stats['total_duration_ms'] / 1000:.2f}s")
    if stats["success"] > 0:
        avg_ms = stats["total_duration_ms"] / stats["success"]
        logger.info(f"Avg duration per success: {avg_ms:.2f}ms")

    if stats["errors"]:
        logger.info("\nErrors encountered:")
        for err in stats["errors"][:10]:
            logger.info(f"  game_id={err['game_id']}: {err['error']}")
        if len(stats["errors"]) > 10:
            logger.info(f"  ... and {len(stats['errors']) - 10} more errors")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Backfill timeline artifacts")
    parser.add_argument("--limit", type=int, help="Limit number of games to process")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    asyncio.run(run_backfill(limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
