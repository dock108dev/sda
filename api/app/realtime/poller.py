"""DB polling engine that detects changes and emits realtime events.

Polls Postgres on configurable intervals for:
  - Game state changes (status, scores, clock, period)
  - New PBP events
  - FairBet odds material changes

All reads only — no writes. Runs as background asyncio tasks.

TODO: Replace DB polling with Postgres LISTEN/NOTIFY or app-level emits
from ingestion writers for lower latency and reduced DB load.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func as sqlfunc
from sqlalchemy import select

from app.db import _get_session_factory
from app.db.odds import FairbetGameOddsWork
from app.db.sports import SportsGame, SportsGamePlay, SportsLeague

from .manager import REALTIME_DEBUG, realtime_manager
from .models import EASTERN, parse_channel, to_et_date_str

logger = logging.getLogger(__name__)

# Polling intervals (seconds) — configurable via env later
POLL_GAMES_INTERVAL_S = 2
POLL_PBP_INTERVAL_S = 1
POLL_FAIRBET_INTERVAL_S = 5

# Max PBP events per game per publish
PBP_BATCH_MAX = 50

# Small overlap window to avoid missing rows due to clock granularity
_OVERLAP_SECONDS = 1

# Per-game PBP seen-id cap (LRU eviction)
_PBP_SEEN_PER_GAME_MAX = 5000


class _LRUSet:
    """Bounded set that evicts oldest entries when full."""

    def __init__(self, maxsize: int) -> None:
        self._data: OrderedDict[int, None] = OrderedDict()
        self._maxsize = maxsize

    def __contains__(self, item: int) -> bool:
        return item in self._data

    def add(self, item: int) -> None:
        if item in self._data:
            self._data.move_to_end(item)
            return
        if len(self._data) >= self._maxsize:
            self._data.popitem(last=False)
        self._data[item] = None

    def __len__(self) -> int:
        return len(self._data)


class DBPoller:
    """Background poller that emits realtime events from DB changes."""

    # Circuit breaker: max consecutive failures before exponential backoff
    _MAX_CONSECUTIVE_FAILURES = 10
    _MAX_BACKOFF_SECONDS = 300

    def __init__(self) -> None:
        self._last_games_check: datetime = datetime.now(UTC)
        self._last_pbp_check: datetime = datetime.now(UTC)
        self._last_fairbet_check: datetime = datetime.now(UTC)
        # Track last-seen updated_at per game to dedupe
        self._game_updated_at: dict[int, datetime] = {}
        # Track last-seen PBP ids per game (bounded LRU)
        self._seen_pbp: dict[int, _LRUSet] = {}
        # Fairbet: track last publish time to avoid spam
        self._last_fairbet_publish: datetime | None = None
        self._tasks: list[asyncio.Task] = []

        # Circuit breaker state per loop
        self._consecutive_failures: dict[str, int] = {"games": 0, "pbp": 0, "fairbet": 0}

        # Debug stats
        self._poll_count: dict[str, int] = {"games": 0, "pbp": 0, "fairbet": 0}
        self._last_poll_duration: dict[str, float] = {"games": 0, "pbp": 0, "fairbet": 0}

    def start(self) -> None:
        """Start all polling loops as background tasks."""
        # Register catch-up callback
        realtime_manager.set_on_first_subscriber(self._on_first_subscriber)

        self._tasks = [
            asyncio.create_task(self._poll_games_loop(), name="poll_games"),
            asyncio.create_task(self._poll_pbp_loop(), name="poll_pbp"),
            asyncio.create_task(self._poll_fairbet_loop(), name="poll_fairbet"),
        ]
        logger.info("realtime_poller_started")

    async def stop(self) -> None:
        """Cancel all polling tasks."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("realtime_poller_stopped")

    def stats(self) -> dict:
        """Return debug stats for the status endpoint."""
        return {
            "poll_count": dict(self._poll_count),
            "last_poll_duration_ms": {
                k: round(v * 1000, 1) for k, v in self._last_poll_duration.items()
            },
            "last_games_check": self._last_games_check.isoformat(),
            "last_pbp_check": self._last_pbp_check.isoformat(),
            "last_fairbet_check": self._last_fairbet_check.isoformat(),
            "tracked_games": len(self._game_updated_at),
            "tracked_pbp_games": len(self._seen_pbp),
            "consecutive_failures": dict(self._consecutive_failures),
        }

    def _backoff_interval(self, loop_name: str, base_interval: float) -> float:
        """Calculate sleep interval with exponential backoff on consecutive failures."""
        failures = self._consecutive_failures.get(loop_name, 0)
        if failures < self._MAX_CONSECUTIVE_FAILURES:
            return base_interval
        extra = min(
            base_interval * (2 ** (failures - self._MAX_CONSECUTIVE_FAILURES)),
            self._MAX_BACKOFF_SECONDS,
        )
        return min(base_interval + extra, self._MAX_BACKOFF_SECONDS)

    # ------------------------------------------------------------------
    # Catch-up: push immediate data when a channel gets its first subscriber
    # ------------------------------------------------------------------

    async def _on_first_subscriber(self, channel: str) -> None:
        """Push immediate data when a channel goes from 0 to 1 subscribers."""
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
        """Push current state for a single game on first subscribe."""
        session_factory = _get_session_factory()
        async with session_factory() as session:
            stmt = (
                select(
                    SportsGame.id,
                    SportsGame.status,
                    SportsGame.home_score,
                    SportsGame.away_score,
                )
                .where(SportsGame.id == game_id)
            )
            result = await session.execute(stmt)
            row = result.one_or_none()

        if row:
            patch = {
                "status": row.status,
                "homeScore": row.home_score,
                "awayScore": row.away_score,
            }
            channel = f"game:{game_id}:summary"
            await realtime_manager.publish(
                channel, "game_patch", {"gameId": str(game_id), "patch": patch}
            )

    async def _catchup_games_list(self, league: str, date_str: str) -> None:
        """Push current state for all games in a league/date on first subscribe."""
        session_factory = _get_session_factory()
        async with session_factory() as session:
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
                    SportsGame.game_date >= datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=EASTERN),
                    SportsGame.game_date < datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=EASTERN) + timedelta(days=1),
                )
            )
            result = await session.execute(stmt)
            rows = result.all()

        channel = f"games:{league}:{date_str}"
        for row in rows:
            patch = {
                "status": row.status,
                "homeScore": row.home_score,
                "awayScore": row.away_score,
            }
            await realtime_manager.publish(
                channel, "game_patch", {"gameId": str(row.id), "patch": patch}
            )

    async def _catchup_fairbet(self) -> None:
        """Signal a refresh on first fairbet subscriber."""
        await realtime_manager.publish(
            "fairbet:odds",
            "fairbet_patch",
            {"patch": {"refresh": True, "reason": "initial_subscribe"}},
        )

    # ------------------------------------------------------------------
    # Game polling
    # ------------------------------------------------------------------

    async def _poll_games_loop(self) -> None:
        """Poll for game state changes."""
        while True:
            try:
                await self._poll_games()
                self._consecutive_failures["games"] = 0
            except asyncio.CancelledError:
                return
            except Exception:
                self._consecutive_failures["games"] += 1
                logger.exception(
                    "poll_games_error",
                    extra={"consecutive_failures": self._consecutive_failures["games"]},
                )
            await asyncio.sleep(self._backoff_interval("games", POLL_GAMES_INTERVAL_S))

    async def _poll_games(self) -> None:
        # Only poll if someone is subscribed to any game-related channel
        active = realtime_manager.active_channels()
        game_channels = {ch for ch in active if ch.startswith("game")}
        if not game_channels:
            return

        t0 = time.monotonic()
        self._poll_count["games"] += 1

        # Extract subscribed leagues+dates and game_ids for selective querying
        subscribed_game_ids: set[int] = set()
        subscribed_league_dates: set[tuple[str, str]] = set()
        for ch in game_channels:
            parsed = parse_channel(ch)
            if not parsed:
                continue
            if parsed["type"] == "game_summary":
                subscribed_game_ids.add(int(parsed["game_id"]))
            elif parsed["type"] == "games_list":
                subscribed_league_dates.add((parsed["league"], parsed["date"]))

        check_since = self._last_games_check - timedelta(seconds=_OVERLAP_SECONDS)
        now = datetime.now(UTC)

        session_factory = _get_session_factory()
        async with session_factory() as session:
            stmt = (
                select(
                    SportsGame.id,
                    SportsGame.league_id,
                    SportsGame.game_date,
                    SportsGame.status,
                    SportsGame.home_score,
                    SportsGame.away_score,
                    SportsGame.updated_at,
                    SportsLeague.code.label("league_code"),
                )
                .join(SportsLeague, SportsGame.league_id == SportsLeague.id)
                .where(SportsGame.updated_at >= check_since)
            )

            # If only specific game_ids are subscribed (no list channels), filter
            if subscribed_game_ids and not subscribed_league_dates:
                stmt = stmt.where(SportsGame.id.in_(subscribed_game_ids))

            result = await session.execute(stmt)
            rows = result.all()

        self._last_games_check = now
        self._last_poll_duration["games"] = time.monotonic() - t0

        for row in rows:
            game_id = row.id

            # Dedupe using updated_at timestamp — skip if row hasn't changed
            prev_updated = self._game_updated_at.get(game_id)
            if prev_updated is not None and row.updated_at <= prev_updated:
                continue
            self._game_updated_at[game_id] = row.updated_at

            patch = {
                "status": row.status,
                "homeScore": row.home_score,
                "awayScore": row.away_score,
            }

            league_code = row.league_code
            game_date_et = to_et_date_str(row.game_date)

            # Publish to game:{gameId}:summary
            summary_channel = f"game:{game_id}:summary"
            if realtime_manager.has_subscribers(summary_channel):
                await realtime_manager.publish(
                    summary_channel,
                    "game_patch",
                    {"gameId": str(game_id), "patch": patch},
                )

            # Publish to games:{league}:{date}
            list_channel = f"games:{league_code}:{game_date_et}"
            if realtime_manager.has_subscribers(list_channel):
                await realtime_manager.publish(
                    list_channel,
                    "game_patch",
                    {"gameId": str(game_id), "patch": patch},
                )

            if REALTIME_DEBUG:
                logger.debug(
                    "poll_games_emit",
                    extra={"game_id": game_id, "patch": patch},
                )

    # ------------------------------------------------------------------
    # PBP polling
    # ------------------------------------------------------------------

    async def _poll_pbp_loop(self) -> None:
        """Poll for new PBP events."""
        while True:
            try:
                await self._poll_pbp()
                self._consecutive_failures["pbp"] = 0
            except asyncio.CancelledError:
                return
            except Exception:
                self._consecutive_failures["pbp"] += 1
                logger.exception(
                    "poll_pbp_error",
                    extra={"consecutive_failures": self._consecutive_failures["pbp"]},
                )
            await asyncio.sleep(self._backoff_interval("pbp", POLL_PBP_INTERVAL_S))

    async def _poll_pbp(self) -> None:
        active = realtime_manager.active_channels()
        pbp_channels = {ch for ch in active if ch.endswith(":pbp")}
        if not pbp_channels:
            return

        t0 = time.monotonic()
        self._poll_count["pbp"] += 1

        # Extract subscribed game IDs
        subscribed_game_ids: set[int] = set()
        for ch in pbp_channels:
            parts = ch.split(":")
            if len(parts) == 3 and parts[0] == "game":
                try:
                    subscribed_game_ids.add(int(parts[1]))
                except ValueError:
                    logger.debug("channel_id_parse_failed", extra={"channel": ch})

        if not subscribed_game_ids:
            return

        check_since = self._last_pbp_check - timedelta(seconds=_OVERLAP_SECONDS)
        now = datetime.now(UTC)

        session_factory = _get_session_factory()
        async with session_factory() as session:
            stmt = (
                select(SportsGamePlay)
                .where(
                    SportsGamePlay.created_at >= check_since,
                    SportsGamePlay.game_id.in_(subscribed_game_ids),
                )
                .order_by(SportsGamePlay.created_at.asc())
            )
            result = await session.execute(stmt)
            plays = result.scalars().all()

        self._last_pbp_check = now
        self._last_poll_duration["pbp"] = time.monotonic() - t0

        # Group by game_id, deduping with per-game bounded LRU sets
        by_game: dict[int, list] = {}
        for play in plays:
            game_seen = self._seen_pbp.setdefault(
                play.game_id, _LRUSet(_PBP_SEEN_PER_GAME_MAX)
            )
            if play.id in game_seen:
                continue
            game_seen.add(play.id)
            by_game.setdefault(play.game_id, []).append(play)

        # Clean up LRU sets for games no longer subscribed
        stale_game_ids = set(self._seen_pbp.keys()) - subscribed_game_ids
        for gid in stale_game_ids:
            del self._seen_pbp[gid]

        for game_id, game_plays in by_game.items():
            channel = f"game:{game_id}:pbp"
            if not realtime_manager.has_subscribers(channel):
                continue

            # Batch into chunks of PBP_BATCH_MAX
            for i in range(0, len(game_plays), PBP_BATCH_MAX):
                batch = game_plays[i : i + PBP_BATCH_MAX]
                events = []
                for p in batch:
                    event: dict = {
                        "eventId": str(p.id),
                        "playIndex": p.play_index,
                        "ts": p.created_at.isoformat() if p.created_at else None,
                        "kind": p.play_type or "play",
                        "text": p.description or "",
                    }
                    if p.raw_data:
                        event["payload"] = p.raw_data
                    if p.home_score is not None:
                        event["homeScore"] = p.home_score
                    if p.away_score is not None:
                        event["awayScore"] = p.away_score
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

    # ------------------------------------------------------------------
    # FairBet polling
    # ------------------------------------------------------------------

    async def _poll_fairbet_loop(self) -> None:
        """Poll for FairBet odds changes."""
        while True:
            try:
                await self._poll_fairbet()
                self._consecutive_failures["fairbet"] = 0
            except asyncio.CancelledError:
                return
            except Exception:
                self._consecutive_failures["fairbet"] += 1
                logger.exception(
                    "poll_fairbet_error",
                    extra={"consecutive_failures": self._consecutive_failures["fairbet"]},
                )
            await asyncio.sleep(self._backoff_interval("fairbet", POLL_FAIRBET_INTERVAL_S))

    async def _poll_fairbet(self) -> None:
        channel = "fairbet:odds"
        if not realtime_manager.has_subscribers(channel):
            return

        t0 = time.monotonic()
        self._poll_count["fairbet"] += 1

        check_since = self._last_fairbet_check - timedelta(seconds=_OVERLAP_SECONDS)
        now = datetime.now(UTC)

        session_factory = _get_session_factory()
        async with session_factory() as session:
            stmt = select(sqlfunc.count()).select_from(
                select(FairbetGameOddsWork.game_id)
                .where(FairbetGameOddsWork.updated_at >= check_since)
                .limit(1)
                .subquery()
            )
            result = await session.execute(stmt)
            count = result.scalar() or 0

        self._last_fairbet_check = now
        self._last_poll_duration["fairbet"] = time.monotonic() - t0

        if count > 0:
            # Only publish if we haven't already published recently (debounce)
            if (
                self._last_fairbet_publish is None
                or (now - self._last_fairbet_publish).total_seconds() >= POLL_FAIRBET_INTERVAL_S
            ):
                self._last_fairbet_publish = now
                await realtime_manager.publish(
                    channel,
                    "fairbet_patch",
                    {"patch": {"refresh": True, "reason": "db_changed"}},
                )


# Singleton poller instance
db_poller = DBPoller()
