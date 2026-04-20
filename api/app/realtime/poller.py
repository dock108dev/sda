"""Catch-up handler: delivers current state when a channel gets its first subscriber.

The DB polling loops that previously detected score/odds/flow changes have been
replaced by Postgres LISTEN/NOTIFY (see ``api/app/realtime/listener.py``).
This module only handles the first-subscriber catch-up path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db import _get_session_factory
from app.db.sports import SportsGame, SportsLeague

from .manager import realtime_manager
from .models import EASTERN, parse_channel

logger = logging.getLogger(__name__)


class DBPoller:
    """Delivers catch-up state on first subscribe. No longer polls for changes."""

    def __init__(self) -> None:
        pass

    def start(self) -> None:
        """Register the first-subscriber catch-up callback."""
        realtime_manager.set_on_first_subscriber(self._on_first_subscriber)
        logger.info("realtime_catchup_started")

    async def stop(self) -> None:
        logger.info("realtime_catchup_stopped")

    def stats(self) -> dict:
        return {}

    # ------------------------------------------------------------------
    # Catch-up
    # ------------------------------------------------------------------

    async def _on_first_subscriber(self, channel: str) -> None:
        parsed = parse_channel(channel)
        if not parsed:
            return
        ch_type = parsed["type"]
        try:
            if ch_type == "game_summary":
                await self._catchup_game_summary(int(parsed["game_id"]))
            elif ch_type == "games_list":
                await self._catchup_games_list(parsed["league"], parsed["date"])
            elif ch_type == "fairbet_odds":
                await self._catchup_fairbet()
        except Exception:
            logger.exception("catchup_error", extra={"channel": channel})

    async def _catchup_game_summary(self, game_id: int) -> None:
        session_factory = _get_session_factory()
        async with session_factory() as session:
            stmt = select(
                SportsGame.id,
                SportsGame.status,
                SportsGame.home_score,
                SportsGame.away_score,
            ).where(SportsGame.id == game_id)
            row = (await session.execute(stmt)).one_or_none()

        if row:
            patch = {
                "status": row.status,
                "score": {"home": row.home_score, "away": row.away_score},
            }
            await realtime_manager.publish(
                f"game:{game_id}:summary",
                "game_patch",
                {"gameId": str(game_id), "patch": patch},
            )

    async def _catchup_games_list(self, league: str, date_str: str) -> None:
        session_factory = _get_session_factory()
        async with session_factory() as session:
            day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=EASTERN)
            stmt = (
                select(
                    SportsGame.id,
                    SportsGame.status,
                    SportsGame.home_score,
                    SportsGame.away_score,
                )
                .join(SportsLeague, SportsGame.league_id == SportsLeague.id)
                .where(
                    SportsLeague.code == league,
                    SportsGame.game_date >= day_start,
                    SportsGame.game_date < day_start + timedelta(days=1),
                )
            )
            rows = (await session.execute(stmt)).all()

        channel = f"games:{league}:{date_str}"
        for row in rows:
            patch = {
                "status": row.status,
                "score": {"home": row.home_score, "away": row.away_score},
            }
            await realtime_manager.publish(
                channel,
                "game_patch",
                {"gameId": str(row.id), "patch": patch},
            )

    async def _catchup_fairbet(self) -> None:
        await realtime_manager.publish(
            "fairbet:odds",
            "fairbet_patch",
            {"patch": {"refresh": True, "reason": "initial_subscribe"}},
        )


db_poller = DBPoller()
