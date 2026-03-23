"""MLB batted ball dataset builder.

Extracts batted ball outcomes from plays where the PA result is a
ball in play (not K/BB/HBP). Uses ``hitData`` from ``raw_data`` JSONB
for exit velocity, launch angle, and spray angle.

Usage::

    builder = MLBBattedBallDatasetBuilder(db)
    rows = await builder.build(date_start="2025-07-01", date_end="2025-10-01")
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.analytics.datasets._profile_mixin import ProfileMixin
from app.analytics.datasets.mlb_pa_labeler import label_pa_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# PA outcomes that represent a ball in play (not K/BB/HBP).
_BIP_OUTCOMES: set[str] = {
    "single",
    "double",
    "triple",
    "home_run",
    "ball_in_play_out",
}

# Map PA outcome labels to batted ball model labels.
_BB_LABEL_MAP: dict[str, str] = {
    "single": "single",
    "double": "double",
    "triple": "triple",
    "home_run": "home_run",
    "ball_in_play_out": "out",
}


def _compute_spray_angle(coord_x: float, coord_y: float) -> float:
    """Derive spray angle from hit coordinates.

    MLB Stats API coordinates use (125.42, 198.27) as home plate.
    Returns angle in degrees.
    """
    dx = coord_x - 125.42
    dy = 198.27 - coord_y
    if dy <= 0:
        return 0.0
    return math.degrees(math.atan2(dx, dy))


class MLBBattedBallDatasetBuilder(ProfileMixin):
    """Build a batted ball outcome dataset from PBP data."""

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
        """Build a batted ball dataset for the given date range.

        Each row contains:
        - game_id, batter_external_ref, pitcher_external_ref
        - exit_velocity, launch_angle, spray_angle
        - outcome (out/single/double/triple/home_run)
        - batter_profile, pitcher_profile (if include_profiles)

        Rows where launchSpeed is null are skipped (weak contact not tracked).
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

        # 4. Extract batted ball rows
        records: list[dict[str, Any]] = []
        stats = {
            "total_plays": 0,
            "bip_plays": 0,
            "labeled_rows": 0,
            "skipped_no_ev": 0,
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

                # Determine PA outcome
                event = raw.get("event") or raw.get("result", {}).get("event", "")
                if not event:
                    event = raw.get("result", {}).get("eventType", "")
                pa_outcome = label_pa_event(event)
                if pa_outcome not in _BIP_OUTCOMES:
                    continue

                stats["bip_plays"] += 1
                bb_label = _BB_LABEL_MAP[pa_outcome]

                # Extract hit data
                hit_data = raw.get("hitData", {})
                exit_velocity = hit_data.get("launchSpeed")
                if exit_velocity is None:
                    stats["skipped_no_ev"] += 1
                    continue

                launch_angle = hit_data.get("launchAngle", 0.0)

                # Spray angle from coordinates
                coords = hit_data.get("coordinates", {})
                coord_x = coords.get("coordX")
                coord_y = coords.get("coordY")
                spray_angle = 0.0
                if coord_x is not None and coord_y is not None:
                    spray_angle = _compute_spray_angle(
                        float(coord_x), float(coord_y),
                    )

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

                # Build profiles
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

                row: dict[str, Any] = {
                    "game_id": game_id,
                    "batter_external_ref": batter_id,
                    "pitcher_external_ref": pitcher_id,
                    "exit_velocity": float(exit_velocity),
                    "launch_angle": float(launch_angle or 0),
                    "spray_angle": round(spray_angle, 2),
                    "outcome": bb_label,
                }

                if batter_profile is not None:
                    row["batter_profile"] = {"metrics": batter_profile}
                if pitcher_profile is not None:
                    row["pitcher_profile"] = {"metrics": pitcher_profile}

                records.append(row)
                stats["labeled_rows"] += 1

        logger.info("mlb_batted_ball_dataset_built", extra=stats)
        return records
