"""Postgres LISTEN/NOTIFY handler for realtime event dispatch.

Replaces the DB polling loops. Each write path issues ``pg_notify`` on
named channels; this coroutine receives them and forwards to the
in-process pub/sub manager.

Channels
--------
game_score_update  — score/status changed (game_id in payload)
odds_update        — fairbet odds updated (game_id in payload)
flow_published     — narrative flow persisted (game_id + flow_id)
pbp_event          — new PBP plays written (game_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from typing import Any

import asyncpg
from sqlalchemy import select

from app.db import _get_session_factory
from app.db.sports import SportsGame, SportsGamePlay, SportsLeague

from .manager import REALTIME_DEBUG, realtime_manager
from .models import to_et_date_str

logger = logging.getLogger(__name__)

_CHANNELS = ("game_score_update", "odds_update", "flow_published", "pbp_event")
_PBP_MAX_GAMES = 500
_PBP_BATCH_MAX = 50


class _LRUDict:
    """Bounded LRU map; evicts the oldest entry on overflow."""

    def __init__(self, maxsize: int) -> None:
        self._data: OrderedDict[int, Any] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: int, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: int, value: Any) -> None:
        self._data.pop(key, None)
        if len(self._data) >= self._maxsize:
            self._data.popitem(last=False)
        self._data[key] = value


class ListenNotifyListener:
    """Dedicated asyncpg LISTEN connection that routes NOTIFY to realtime_manager.

    One connection for all LISTEN channels. Regular DB queries stay on the
    SQLAlchemy pool so notification callbacks are never blocked by slow queries.
    """

    _INITIAL_BACKOFF = 1.0
    _MAX_BACKOFF = 60.0
    _KEEPALIVE_INTERVAL = 30.0

    def __init__(self) -> None:
        self._dsn: str | None = None
        self._task: asyncio.Task | None = None
        self._conn: asyncpg.Connection | None = None
        self._pbp_cursor = _LRUDict(_PBP_MAX_GAMES)
        # Tracks last-known status per game_id to detect phase changes.
        self._game_status_cache: _LRUDict = _LRUDict(500)
        self._notify_count: dict[str, int] = {ch: 0 for ch in _CHANNELS}
        self._reconnect_count: int = 0

    def _get_dsn(self) -> str:
        if self._dsn is None:
            from app.config import settings

            # SA async URL → plain asyncpg DSN
            self._dsn = settings.database_url.replace(
                "postgresql+asyncpg://", "postgresql://"
            )
        return self._dsn

    def start(self) -> None:
        self._task = asyncio.create_task(self._listen_loop(), name="listen_notify")
        logger.info("listen_notify_listener_started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        conn = self._conn
        if conn and not conn.is_closed():
            try:
                await conn.close()
            except Exception:
                pass
        logger.info("listen_notify_listener_stopped")

    def stats(self) -> dict:
        return {
            "notify_count": dict(self._notify_count),
            "reconnect_count": self._reconnect_count,
        }

    # ------------------------------------------------------------------
    # Reconnect loop
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        backoff = self._INITIAL_BACKOFF
        while True:
            conn: asyncpg.Connection | None = None
            try:
                conn = await asyncpg.connect(self._get_dsn())
                self._conn = conn
                backoff = self._INITIAL_BACKOFF
                for ch in _CHANNELS:
                    await conn.add_listener(ch, self._on_notify)
                logger.info(
                    "listen_notify_connected",
                    extra={"channels": list(_CHANNELS)},
                )
                # Keep-alive ping loop
                while not conn.is_closed():
                    await asyncio.sleep(self._KEEPALIVE_INTERVAL)
                    try:
                        await conn.execute("SELECT 1")
                    except Exception:
                        logger.warning("listen_notify_keepalive_failed", exc_info=True)
                        break

            except asyncio.CancelledError:
                return
            except (asyncpg.PostgresError, OSError) as exc:
                self._reconnect_count += 1
                logger.warning(
                    "listen_notify_error",
                    extra={
                        "error": str(exc),
                        "backoff_s": backoff,
                        "reconnects": self._reconnect_count,
                    },
                )
            except Exception:
                self._reconnect_count += 1
                logger.exception(
                    "listen_notify_unexpected_error",
                    extra={"backoff_s": backoff},
                )
            finally:
                if conn and not conn.is_closed():
                    try:
                        for ch in _CHANNELS:
                            await conn.remove_listener(ch, self._on_notify)
                        await conn.close()
                    except Exception:
                        pass

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._MAX_BACKOFF)

    # ------------------------------------------------------------------
    # Notification callback (sync; called by asyncpg in the event loop)
    # ------------------------------------------------------------------

    def _on_notify(
        self,
        conn: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        try:
            data = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            logger.warning(
                "listen_notify_bad_payload",
                extra={"channel": channel, "payload": payload[:200]},
            )
            return

        self._notify_count[channel] = self._notify_count.get(channel, 0) + 1
        if REALTIME_DEBUG:
            logger.debug(
                "listen_notify_received",
                extra={"channel": channel, "game_id": data.get("game_id")},
            )

        asyncio.ensure_future(self._dispatch(channel, data))

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, channel: str, data: dict) -> None:
        try:
            if channel == "game_score_update":
                await self._handle_game_score_update(data)
            elif channel == "odds_update":
                await self._handle_odds_update(data)
            elif channel == "flow_published":
                await self._handle_flow_published(data)
            elif channel == "pbp_event":
                await self._handle_pbp_event(data)
        except Exception:
            logger.exception(
                "listen_notify_dispatch_error",
                extra={"channel": channel, "game_id": data.get("game_id")},
            )

    async def _handle_game_score_update(self, data: dict) -> None:
        game_id = data.get("game_id")
        if not game_id:
            return

        summary_ch = f"game:{game_id}:summary"
        active = realtime_manager.active_channels()
        has_summary = realtime_manager.has_subscribers(summary_ch)
        has_list = any(ch.startswith("games:") for ch in active)

        if not has_summary and not has_list:
            return

        # Single PK lookup — fetch fresh state rather than trusting the payload.
        session_factory = _get_session_factory()
        async with session_factory() as session:
            stmt = (
                select(
                    SportsGame.id,
                    SportsGame.status,
                    SportsGame.home_score,
                    SportsGame.away_score,
                    SportsGame.game_date,
                    SportsLeague.code.label("league_code"),
                )
                .join(SportsLeague, SportsGame.league_id == SportsLeague.id)
                .where(SportsGame.id == game_id)
            )
            row = (await session.execute(stmt)).one_or_none()

        if not row:
            return

        payload_patch = {
            "status": row.status,
            "score": {"home": row.home_score, "away": row.away_score},
        }

        # Determine event type: phase_change when status transitions, patch otherwise.
        prev_status = self._game_status_cache.get(game_id)
        is_phase_change = prev_status is not None and prev_status != row.status
        event_type = "phase_change" if is_phase_change else "patch"
        self._game_status_cache.set(game_id, row.status)

        if has_summary:
            await realtime_manager.publish(
                summary_ch,
                event_type,
                {"gameId": str(game_id), "patch": payload_patch},
            )

        if has_list:
            game_date_et = to_et_date_str(row.game_date)
            list_ch = f"games:{row.league_code}:{game_date_et}"
            if realtime_manager.has_subscribers(list_ch):
                await realtime_manager.publish(
                    list_ch,
                    event_type,
                    {"gameId": str(game_id), "patch": payload_patch},
                )

    async def _handle_odds_update(self, data: dict) -> None:
        channel = "fairbet:odds"
        if realtime_manager.has_subscribers(channel):
            await realtime_manager.publish(
                channel,
                "fairbet_patch",
                {"patch": {"refresh": True, "reason": "db_changed"}},
            )

    async def _handle_flow_published(self, data: dict) -> None:
        game_id = data.get("game_id")
        if not game_id:
            return
        channel = f"game:{game_id}:summary"
        if realtime_manager.has_subscribers(channel):
            await realtime_manager.publish(
                channel,
                "flow_published",
                {"gameId": str(game_id), "flowId": data.get("flow_id")},
            )

    async def _handle_pbp_event(self, data: dict) -> None:
        game_id = data.get("game_id")
        if not game_id:
            return
        channel = f"game:{game_id}:pbp"
        if not realtime_manager.has_subscribers(channel):
            return

        last_seen_id = self._pbp_cursor.get(game_id, 0)
        session_factory = _get_session_factory()
        async with session_factory() as session:
            stmt = (
                select(SportsGamePlay)
                .where(
                    SportsGamePlay.game_id == game_id,
                    SportsGamePlay.id > last_seen_id,
                )
                .order_by(SportsGamePlay.id.asc())
                .limit(_PBP_BATCH_MAX)
            )
            plays = (await session.execute(stmt)).scalars().all()

        if not plays:
            return

        self._pbp_cursor.set(game_id, plays[-1].id)

        events = []
        for p in plays:
            event: dict = {
                "eventId": str(p.id),
                "playIndex": p.play_index,
                "ts": p.created_at.isoformat() if p.created_at else None,
                "kind": p.play_type or "play",
                "text": p.description or "",
            }
            if p.raw_data:
                event["payload"] = p.raw_data
            if p.home_score is not None or p.away_score is not None:
                event["score"] = {"home": p.home_score, "away": p.away_score}
            if p.quarter is not None:
                event["period"] = p.quarter
            if p.game_clock:
                event["clock"] = p.game_clock
            events.append(event)

        await realtime_manager.publish(
            channel,
            "pbp_append",
            {"gameId": str(game_id), "events": events},
        )


# Singleton — start()/stop() wired in main.py lifespan
pg_listener = ListenNotifyListener()
