"""Closing line capture: snapshot the last pre-game odds when a game goes LIVE.

Rules:
  - Capture once, at the moment game transitions PRE -> LIVE
  - Source from existing SportsGameOdds (pregame data already in DB)
  - If no pregame odds exist, fetch from provider immediately and mark as late_capture
  - Closing lines persist permanently in the closing_lines table
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..db import get_session
from ..db import db_models
from ..logging import logger


def capture_closing_lines(game_id: int, league_code: str) -> int:
    """Capture closing lines for a game from existing pregame odds.

    Returns the number of closing line rows inserted.
    """
    with get_session() as session:
        # Check if we already have closing lines for this game
        existing = session.execute(
            select(db_models.ClosingLine.id)
            .where(db_models.ClosingLine.game_id == game_id)
            .limit(1)
        ).scalar_one_or_none()

        if existing is not None:
            logger.debug("closing_lines_already_captured", game_id=game_id)
            return 0

        # Pull latest pregame odds from SportsGameOdds (is_closing_line=True)
        stmt = (
            select(db_models.SportsGameOdds)
            .where(
                db_models.SportsGameOdds.game_id == game_id,
                db_models.SportsGameOdds.is_closing_line.is_(True),
                db_models.SportsGameOdds.market_category == "mainline",
            )
        )
        odds_rows = session.execute(stmt).scalars().all()

        if not odds_rows:
            logger.warning(
                "closing_lines_no_pregame_odds",
                game_id=game_id,
                league=league_code,
            )
            return 0

        now = datetime.now(UTC)
        inserted = 0

        for row in odds_rows:
            values = {
                "game_id": game_id,
                "league": league_code,
                "market_key": row.source_key or row.market_type,
                "selection": row.side or "",
                "line_value": row.line,
                "price_american": row.price or 0,
                "provider": row.book,
                "captured_at": now,
                "source_type": "closing",
            }

            ins = pg_insert(db_models.ClosingLine).values(**values)
            ins = ins.on_conflict_do_nothing(
                index_elements=[
                    "game_id", "provider", "market_key", "selection", "line_value"
                ]
            )
            result = session.execute(ins)
            if result.rowcount > 0:
                inserted += 1

        session.commit()

        logger.info(
            "closing_lines_captured",
            game_id=game_id,
            league=league_code,
            rows_inserted=inserted,
            odds_available=len(odds_rows),
        )
        return inserted


def capture_closing_lines_from_provider(
    game_id: int, league_code: str
) -> int:
    """Fallback: fetch closing lines from provider right now.

    Used when no pregame odds exist in DB at the time game goes LIVE.
    Marks source_type as 'late_capture'.
    """
    from ..odds.synchronizer import OddsSynchronizer
    from ..models import IngestionConfig
    from ..utils.datetime_utils import today_et

    # Fetch current odds from provider
    sync = OddsSynchronizer()
    today = today_et()
    config = IngestionConfig(
        league_code=league_code,
        start_date=today,
        end_date=today,
        odds=True,
        boxscores=False,
        social=False,
        pbp=False,
    )

    try:
        sync.sync(config)
    except Exception as exc:
        logger.warning(
            "closing_lines_provider_fetch_error",
            game_id=game_id,
            error=str(exc),
        )

    # Now try to capture from the freshly-synced data
    count = capture_closing_lines(game_id, league_code)

    if count > 0:
        # Update source_type to late_capture
        with get_session() as session:
            session.execute(
                db_models.ClosingLine.__table__.update()
                .where(
                    db_models.ClosingLine.game_id == game_id,
                    db_models.ClosingLine.source_type == "closing",
                )
                .values(source_type="late_capture")
            )
            session.commit()

    logger.info(
        "closing_lines_late_capture",
        game_id=game_id,
        league=league_code,
        rows=count,
    )
    return count
