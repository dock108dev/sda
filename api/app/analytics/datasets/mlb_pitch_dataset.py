"""MLB pitch-level dataset builder.

Extracts individual pitch outcomes from ``SportsGamePlay.raw_data``
JSONB (which contains MLB Stats API ``playEvents`` arrays) and
assembles training rows with point-in-time batter/pitcher profiles.

Usage::

    builder = MLBPitchDatasetBuilder(db)
    rows = await builder.build(date_start="2025-07-01", date_end="2025-10-01")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.analytics.datasets._profile_mixin import ProfileMixin
from app.analytics.datasets.mlb_pitch_labeler import label_pitch_code

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MLBPitchDatasetBuilder(ProfileMixin):
    """Build a pitch-outcome dataset from PBP play events."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def build(
        self,
        *,
        date_start: str | None = None,
        date_end: str | None = None,
        rolling_window: int = 30,
        include_profiles: bool = True,
        min_batter_games: int = 5,
        min_pitcher_games: int = 3,
    ) -> list[dict[str, Any]]:
        """Build a pitch-outcome dataset for the given date range.

        Each row contains:
        - game_id, batter_external_ref, pitcher_external_ref
        - count_balls, count_strikes (before the pitch)
        - pitch_zone (1-14), pitch_speed
        - outcome (canonical pitch outcome label)
        - batter_profile, pitcher_profile (if include_profiles)
        """
        from sqlalchemy import select

        from app.db.sports import SportsGame, SportsGamePlay

        db = self._db

        dt_start = (
            datetime.strptime(date_start, "%Y-%m-%d").replace(tzinfo=UTC)
            if date_start else None
        )
        dt_end = (
            datetime.strptime(date_end, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=UTC
            )
            if date_end else None
        )

        # 1. Load completed games
        game_stmt = (
            select(SportsGame)
            .where(SportsGame.status.in_(["final", "archived"]))
            .order_by(SportsGame.game_date.asc())
        )
        if dt_start:
            game_stmt = game_stmt.where(SportsGame.game_date >= dt_start)
        if dt_end:
            game_stmt = game_stmt.where(SportsGame.game_date <= dt_end)

        games_result = await db.execute(game_stmt)
        games = games_result.scalars().all()
        if not games:
            return []

        game_map = {g.id: g for g in games}

        # 2. Load PBP plays via date-range join (avoids massive IN clause)
        plays_stmt = (
            select(SportsGamePlay)
            .join(SportsGame, SportsGame.id == SportsGamePlay.game_id)
            .where(SportsGame.status.in_(["final", "archived"]))
            .order_by(SportsGamePlay.game_id, SportsGamePlay.play_index)
        )
        if dt_start:
            plays_stmt = plays_stmt.where(SportsGame.game_date >= dt_start)
        if dt_end:
            plays_stmt = plays_stmt.where(SportsGame.game_date <= dt_end)
        plays_result = await db.execute(plays_stmt)
        all_plays = plays_result.scalars().all()

        plays_by_game: dict[int, list] = defaultdict(list)
        for play in all_plays:
            plays_by_game[play.game_id].append(play)

        # 3. Pre-load rolling profiles
        batter_history = None
        pitcher_history = None

        if include_profiles:
            batter_history, pitcher_history, _ = (
                await self._load_profile_histories(dt_start, dt_end, rolling_window)
            )

        # 4. Extract pitches from playEvents
        records: list[dict[str, Any]] = []
        stats = {
            "total_plays": 0,
            "total_pitches": 0,
            "labeled_pitches": 0,
            "skipped_no_label": 0,
            "skipped_no_profile": 0,
        }

        for game_id, game_plays in plays_by_game.items():
            game = game_map.get(game_id)
            if game is None:
                continue

            game_date_str = str(game.game_date)

            for play in game_plays:
                stats["total_plays"] += 1
                raw = play.raw_data or {}

                matchup = raw.get("matchup", {})
                batter_id = str(
                    matchup.get("batter", {}).get("id", "")
                    or raw.get("batter_id", "")
                    or play.player_id
                    or ""
                )
                pitcher_id = str(
                    matchup.get("pitcher", {}).get("id", "")
                    or raw.get("pitcher_id", "")
                    or ""
                )
                if not batter_id or not pitcher_id:
                    continue

                # Build profiles once per PA (shared across all pitches)
                batter_profile = None
                pitcher_profile = None
                if include_profiles and batter_history is not None:
                    batter_profile = self._build_player_profile(
                        batter_id, batter_history, game_date_str,
                        rolling_window, min_batter_games,
                    )
                    pitcher_profile = self._build_pitcher_profile(
                        pitcher_id, pitcher_history, game_date_str,
                        rolling_window, min_pitcher_games,
                    )
                    if batter_profile is None or pitcher_profile is None:
                        stats["skipped_no_profile"] += 1
                        continue

                # Iterate playEvents for pitches
                play_events = raw.get("playEvents", [])
                for event in play_events:
                    if not event.get("isPitch", False):
                        continue

                    stats["total_pitches"] += 1

                    details = event.get("details", {})
                    code = details.get("code", "")
                    outcome = label_pitch_code(code)
                    if outcome is None:
                        stats["skipped_no_label"] += 1
                        continue

                    count = event.get("count", {})
                    pitch_data = event.get("pitchData", {})

                    row: dict[str, Any] = {
                        "game_id": game_id,
                        "batter_external_ref": batter_id,
                        "pitcher_external_ref": pitcher_id,
                        "count_balls": count.get("balls", 0),
                        "count_strikes": count.get("strikes", 0),
                        "pitch_zone": pitch_data.get("zone", 0),
                        "pitch_speed": pitch_data.get("startSpeed", 0.0),
                        "outcome": outcome,
                    }

                    if batter_profile is not None:
                        row["batter_profile"] = {"metrics": batter_profile}
                    if pitcher_profile is not None:
                        row["pitcher_profile"] = {"metrics": pitcher_profile}

                    records.append(row)
                    stats["labeled_pitches"] += 1

        logger.info("mlb_pitch_dataset_built", extra=stats)
        return records
