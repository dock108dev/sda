#!/usr/bin/env python3
"""CLI script: enqueue flow generation for FINAL/RECAP_FAILED games with no flow artifact.

Usage:
    python scripts/backfill_missing_flows.py [--days N] [--dry-run]

Options:
    --days N      Look-back window in days (default: 7)
    --dry-run     Print eligible games without enqueuing tasks

Idempotency: The NX lock inside trigger_flow_for_game (key:
pipeline_lock:trigger_flow_for_game:<id>) prevents double-dispatch when
re-run over the same window within the lock TTL (1 hour).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Bootstrap: ensure both api/ and scraper/ are importable.
# ---------------------------------------------------------------------------
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("api", "scraper"):
    _p = os.path.join(_REPO, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=7, help="Look-back window in days (default: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Print eligible games without enqueuing")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Import after path setup
    from sqlalchemy import create_engine, exists, not_, or_, text
    from sqlalchemy.orm import Session

    from app.db.sports import GameStatus, SportsGame
    from app.db.flow import SportsGameTimelineArtifact

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("ERROR: DATABASE_URL environment variable is required")

    engine = create_engine(db_url, echo=False)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    eligible_statuses = [GameStatus.final.value, GameStatus.recap_failed.value]

    with Session(engine) as session:
        games = (
            session.query(SportsGame)
            .filter(
                SportsGame.status.in_(eligible_statuses),
                SportsGame.game_date >= cutoff,
                not_(
                    exists().where(SportsGameTimelineArtifact.game_id == SportsGame.id)
                ),
            )
            .order_by(SportsGame.game_date.asc())
            .all()
        )
        game_ids = [g.id for g in games]

    print(f"Found {len(game_ids)} eligible game(s) in the past {args.days} day(s).")

    if not game_ids:
        return

    if args.dry_run:
        print("Dry-run mode — not enqueuing. Eligible game IDs:")
        for gid in game_ids:
            print(f"  {gid}")
        return

    # Dispatch via Celery (requires CELERY_BROKER_URL / REDIS_URL)
    from sports_scraper.jobs.flow_trigger_tasks import trigger_flow_for_game

    _STAGGER_SECONDS = 30
    enqueued = 0
    for idx, game_id in enumerate(game_ids):
        countdown = idx * _STAGGER_SECONDS
        trigger_flow_for_game.apply_async(args=[game_id], countdown=countdown)
        print(f"  Enqueued game {game_id} (countdown={countdown}s)")
        enqueued += 1

    print(f"Done. Enqueued {enqueued} task(s).")


if __name__ == "__main__":
    main()
