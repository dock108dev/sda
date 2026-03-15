"""True historical MLB plate-appearance dataset builder.

Replaces the heuristic-based PA outcome derivation with real play-by-play
event labels. Generates one row per historical PA with point-in-time
batter/pitcher/fielding profiles.

Usage::

    builder = MLBPADatasetBuilder(db)
    rows = await builder.build(date_start="2025-07-01", date_end="2025-10-01")
    # Each row has: game context, batter/pitcher refs, outcome label,
    # and optionally assembled point-in-time feature profiles.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.analytics.datasets.mlb_pa_labeler import label_pa_event
from app.tasks._training_helpers import build_rolling_profile, stats_to_metrics

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Maps MLB Stats API at-bat event strings to our canonical PA outcomes.
# Populated by mlb_pa_labeler.


class MLBPADatasetBuilder:
    """Build a true PA dataset from PBP play events with point-in-time profiles."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def build(
        self,
        *,
        date_start: str | None = None,
        date_end: str | None = None,
        rolling_window: int = 30,
        include_profiles: bool = True,
        include_fielding: bool = False,
        min_batter_games: int = 5,
        min_pitcher_games: int = 3,
    ) -> list[dict[str, Any]]:
        """Build a PA dataset for the given date range.

        Each row contains:
        - game_id, game_date, season
        - batting_team_id, fielding_team_id
        - batter_external_ref, pitcher_external_ref
        - inning, half (top/bottom), outs_before
        - batter_hand, pitcher_hand (if available)
        - outcome (canonical PA outcome label)
        - batter_profile, pitcher_profile (if include_profiles)
        - team_fielding (if include_fielding)

        Point-in-time safety: profiles use only data from before the game.
        """
        from sqlalchemy import select

        from app.db.sports import SportsGame, SportsGamePlay

        db = self._db

        # Parse date bounds
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

        # 1. Load completed games in range
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
        game_ids = list(game_map.keys())

        # 2. Load PBP plays for these games (at_bat type plays with raw_data)
        plays_stmt = (
            select(SportsGamePlay)
            .where(SportsGamePlay.game_id.in_(game_ids))
            .order_by(SportsGamePlay.game_id, SportsGamePlay.play_index)
        )
        plays_result = await db.execute(plays_stmt)
        all_plays = plays_result.scalars().all()

        # Group plays by game
        plays_by_game: dict[int, list] = defaultdict(list)
        for play in all_plays:
            plays_by_game[play.game_id].append(play)

        # 3. If profiles requested, pre-load rolling profile data
        batter_history = None
        pitcher_history = None
        team_history = None
        fielding_by_team = None

        if include_profiles:
            batter_history, pitcher_history, team_history = (
                await self._load_profile_histories(
                    game_ids, dt_end, rolling_window
                )
            )

        if include_fielding:
            fielding_by_team = await self._load_team_fielding(game_ids)

        # 4. Extract PAs from plays
        records = []
        stats = {"total_plays": 0, "labeled_pas": 0, "skipped_no_label": 0,
                 "skipped_no_profile": 0}

        for game_id, game_plays in plays_by_game.items():
            game = game_map.get(game_id)
            if game is None:
                continue

            game_date_str = str(game.game_date)

            for play in game_plays:
                stats["total_plays"] += 1
                raw = play.raw_data or {}

                # Extract PA-relevant fields from raw_data
                # MLB PBP stores atBat data in raw_data with event result
                event = raw.get("event") or raw.get("result", {}).get("event", "")
                if not event:
                    # Try play description based labeling
                    event = raw.get("result", {}).get("eventType", "")

                outcome = label_pa_event(event)
                if outcome is None:
                    stats["skipped_no_label"] += 1
                    continue

                # Extract context
                about = raw.get("about", {})
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
                    stats["skipped_no_label"] += 1
                    continue

                inning = about.get("inning") or play.quarter or 0
                half_inning = about.get("halfInning", "top")
                is_top = half_inning == "top"
                outs_before = about.get("outs", 0)

                batting_team_id = (
                    game.away_team_id if is_top else game.home_team_id
                )
                fielding_team_id = (
                    game.home_team_id if is_top else game.away_team_id
                )

                batter_hand = matchup.get("batSide", {}).get("code", "")
                pitcher_hand = matchup.get("pitchHand", {}).get("code", "")

                # Compute score differential from the batter's perspective
                try:
                    home_score = int(play.home_score or 0)
                    away_score = int(play.away_score or 0)
                except (TypeError, ValueError):
                    home_score = away_score = 0
                score_diff = (
                    (away_score - home_score) if is_top
                    else (home_score - away_score)
                )

                row: dict[str, Any] = {
                    "game_id": game_id,
                    "game_date": game_date_str,
                    "season": game.season,
                    "batting_team_id": batting_team_id,
                    "fielding_team_id": fielding_team_id,
                    "batter_external_ref": batter_id,
                    "pitcher_external_ref": pitcher_id,
                    "inning": inning,
                    "half": "top" if is_top else "bottom",
                    "outs_before": outs_before,
                    "batter_hand": batter_hand,
                    "pitcher_hand": pitcher_hand,
                    "score_diff": score_diff,
                    "outcome": outcome,
                }

                # Assemble profiles
                if include_profiles and batter_history is not None:
                    batter_profile = self._build_player_profile(
                        batter_id, batter_history, game_date_str,
                        rolling_window, min_batter_games,
                    )
                    pitcher_profile = self._build_pitcher_profile(
                        pitcher_id, pitcher_history, game_date_str,
                        rolling_window, min_pitcher_games,
                    )
                    # Fall back to team profile for pitcher if no individual data
                    if pitcher_profile is None and team_history:
                        pitcher_profile = build_rolling_profile(
                            team_history.get(fielding_team_id, []),
                            before_date=game_date_str,
                            window=rolling_window,
                        )

                    if batter_profile is None or pitcher_profile is None:
                        stats["skipped_no_profile"] += 1
                        continue

                    row["batter_profile"] = {"metrics": batter_profile}
                    row["pitcher_profile"] = {"metrics": pitcher_profile}
                    row["matchup"] = {
                        "batter_hand": batter_hand,
                        "pitcher_hand": pitcher_hand,
                        "inning": float(inning),
                        "outs": float(outs_before),
                        "score_diff": float(score_diff),
                    }

                if include_fielding and fielding_by_team:
                    team_def = fielding_by_team.get(fielding_team_id)
                    if team_def:
                        row["team_fielding"] = team_def

                records.append(row)
                stats["labeled_pas"] += 1

        logger.info("mlb_pa_dataset_built", extra=stats)
        return records

    def _build_player_profile(
        self,
        player_ref: str,
        history: dict[str, list[tuple[str, Any]]],
        before_date: str,
        window: int,
        min_games: int,
    ) -> dict[str, float] | None:
        """Build a player rolling profile from pre-loaded history.

        Merges Statcast metrics (from MLBPlayerAdvancedStats) with standard
        batting stats (from SportsPlayerBoxscore) when boxscore history is
        available.
        """
        player_games = history.get(player_ref, [])
        prior = [s for d, s in player_games if d < before_date]
        if len(prior) < min_games:
            return None
        recent = prior[-window:]
        metrics_list = [stats_to_metrics(s) for s in recent]
        aggregated: dict[str, float] = {}
        for key in metrics_list[0]:
            vals = [m[key] for m in metrics_list if key in m]
            if vals:
                aggregated[key] = round(sum(vals) / len(vals), 4)

        # Merge standard batting stats from boxscore history if available
        box_history = getattr(self, "_boxscore_history", None)
        if box_history:
            box_games = box_history.get(player_ref, [])
            box_prior = [raw for d, raw in box_games if d < before_date]
            if box_prior:
                box_recent = box_prior[-window:]
                box_metrics = [_boxscore_batting_metrics(raw) for raw in box_recent]
                for key in box_metrics[0]:
                    vals = [m[key] for m in box_metrics if key in m]
                    if vals:
                        aggregated[key] = round(sum(vals) / len(vals), 4)

        return aggregated

    def _build_pitcher_profile(
        self,
        pitcher_ref: str,
        history: dict[str, list[tuple[str, Any]]],
        before_date: str,
        window: int,
        min_games: int,
    ) -> dict[str, float] | None:
        """Build a pitcher rolling profile from pitcher game stats history."""
        pitcher_games = history.get(pitcher_ref, [])
        prior = [s for d, s in pitcher_games if d < before_date]
        if len(prior) < min_games:
            return None
        recent = prior[-window:]
        metrics_list = [_pitcher_stats_to_metrics(s) for s in recent]
        if not metrics_list:
            return None
        aggregated: dict[str, float] = {}
        for key in metrics_list[0]:
            vals = [m[key] for m in metrics_list if key in m]
            if vals:
                aggregated[key] = round(sum(vals) / len(vals), 4)
        return aggregated

    async def _load_profile_histories(
        self,
        game_ids: list[int],
        dt_end: datetime | None,
        rolling_window: int,
    ) -> tuple[
        dict[str, list[tuple[str, Any]]],
        dict[str, list[tuple[str, Any]]],
        dict[int, list[tuple[str, Any]]],
    ]:
        """Pre-load all batter, pitcher, and team history for profile assembly."""
        from sqlalchemy import select

        from app.db.mlb_advanced import (
            MLBGameAdvancedStats,
            MLBPitcherGameStats,
            MLBPlayerAdvancedStats,
        )
        from app.db.sports import SportsGame

        db = self._db

        # Batter history from MLBPlayerAdvancedStats
        batter_stmt = (
            select(MLBPlayerAdvancedStats, SportsGame.game_date)
            .join(SportsGame, SportsGame.id == MLBPlayerAdvancedStats.game_id)
            .where(SportsGame.status.in_(["final", "archived"]))
            .order_by(SportsGame.game_date.asc())
        )
        if dt_end:
            batter_stmt = batter_stmt.where(SportsGame.game_date <= dt_end)
        batter_result = await db.execute(batter_stmt)

        batter_history: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        for stats_row, game_date in batter_result:
            batter_history[stats_row.player_external_ref].append(
                (str(game_date), stats_row)
            )

        # Pitcher history from MLBPitcherGameStats
        pitcher_stmt = (
            select(MLBPitcherGameStats, SportsGame.game_date)
            .join(SportsGame, SportsGame.id == MLBPitcherGameStats.game_id)
            .where(SportsGame.status.in_(["final", "archived"]))
            .order_by(SportsGame.game_date.asc())
        )
        if dt_end:
            pitcher_stmt = pitcher_stmt.where(SportsGame.game_date <= dt_end)
        pitcher_result = await db.execute(pitcher_stmt)

        pitcher_history: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        for stats_row, game_date in pitcher_result:
            pitcher_history[stats_row.player_external_ref].append(
                (str(game_date), stats_row)
            )

        # Team history for fallback pitcher profiles
        team_stmt = (
            select(MLBGameAdvancedStats, SportsGame.game_date)
            .join(SportsGame, SportsGame.id == MLBGameAdvancedStats.game_id)
            .where(SportsGame.status.in_(["final", "archived"]))
            .order_by(SportsGame.game_date.asc())
        )
        if dt_end:
            team_stmt = team_stmt.where(SportsGame.game_date <= dt_end)
        team_result = await db.execute(team_stmt)

        team_history: dict[int, list[tuple[str, Any]]] = defaultdict(list)
        for stats_row, game_date in team_result:
            team_history[stats_row.team_id].append((str(game_date), stats_row))

        # Batter boxscore history from SportsPlayerBoxscore for standard batting stats
        from app.db.sports import SportsPlayerBoxscore

        box_stmt = (
            select(SportsPlayerBoxscore, SportsGame.game_date)
            .join(SportsGame, SportsGame.id == SportsPlayerBoxscore.game_id)
            .where(
                SportsGame.status.in_(["final", "archived"]),
                SportsPlayerBoxscore.player_external_ref.isnot(None),
            )
            .order_by(SportsGame.game_date.asc())
        )
        if dt_end:
            box_stmt = box_stmt.where(SportsGame.game_date <= dt_end)
        box_result = await db.execute(box_stmt)

        boxscore_history: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        for box_row, game_date in box_result:
            raw = box_row.stats or box_row.raw_stats_json or {}
            if raw.get("player_role") == "batter" and box_row.player_external_ref:
                boxscore_history[box_row.player_external_ref].append(
                    (str(game_date), raw)
                )

        # Attach to batter_history metadata for profile building
        self._boxscore_history = boxscore_history

        return batter_history, pitcher_history, team_history

    async def _load_team_fielding(
        self,
        game_ids: list[int],
    ) -> dict[int, dict[str, float]]:
        """Load team-level fielding aggregates for defensive context."""
        from sqlalchemy import func, select

        from app.db.mlb_advanced import MLBPlayerFieldingStats

        db = self._db

        stmt = (
            select(
                MLBPlayerFieldingStats.team_id,
                func.avg(MLBPlayerFieldingStats.outs_above_average).label("avg_oaa"),
                func.avg(MLBPlayerFieldingStats.defensive_runs_saved).label("avg_drs"),
                func.count().label("player_count"),
            )
            .where(MLBPlayerFieldingStats.team_id.isnot(None))
            .group_by(MLBPlayerFieldingStats.team_id)
        )
        result = await db.execute(stmt)

        fielding: dict[int, dict[str, float]] = {}
        for row in result:
            fielding[row.team_id] = {
                "team_oaa": round(float(row.avg_oaa or 0), 4),
                "team_drs": round(float(row.avg_drs or 0), 4),
                "team_defensive_value": 0.0,
                "fielding_player_count": int(row.player_count),
            }
        return fielding


def _boxscore_batting_metrics(raw: dict) -> dict[str, float]:
    """Extract standard batting metrics from SportsPlayerBoxscore raw_stats.

    These supplement the Statcast-derived metrics from MLBPlayerAdvancedStats,
    giving the model access to traditional slash-line stats (AVG/OBP/SLG)
    and counting stats (H, HR, BB, K) that Statcast alone doesn't capture.
    """
    ab = float(raw.get("atBats", 0) or 0)
    h = float(raw.get("hits", 0) or 0)
    hr = float(raw.get("homeRuns", 0) or 0)
    bb = float(raw.get("baseOnBalls", 0) or 0)
    so = float(raw.get("strikeOuts", 0) or 0)
    doubles = float(raw.get("doubles", 0) or 0)
    triples = float(raw.get("triples", 0) or 0)
    rbi = float(raw.get("rbi", 0) or 0)

    def _parse_float(val: Any, default: float) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    return {
        "box_at_bats": ab,
        "box_hits": h,
        "box_home_runs": hr,
        "box_walks": bb,
        "box_strikeouts": so,
        "box_doubles": doubles,
        "box_triples": triples,
        "box_rbi": rbi,
        "box_avg": _parse_float(raw.get("avg"), 0.250),
        "box_obp": _parse_float(raw.get("obp"), 0.320),
        "box_slg": _parse_float(raw.get("slg"), 0.400),
        "box_ops": _parse_float(raw.get("ops"), 0.720),
        # Per-AB rates for single-game context
        "box_k_rate": (so / ab) if ab > 0 else 0.22,
        "box_bb_rate": (bb / (ab + bb)) if (ab + bb) > 0 else 0.08,
        "box_hr_rate": (hr / ab) if ab > 0 else 0.03,
        "box_iso": ((doubles + 2 * triples + 3 * hr) / ab) if ab > 0 else 0.150,
    }


def _pitcher_stats_to_metrics(stats: Any) -> dict[str, float]:
    """Convert MLBPitcherGameStats to a metrics dict for rolling profiles."""
    bf = stats.batters_faced or 0
    ip = stats.innings_pitched or 0.0

    total_swings = (stats.zone_swings or 0) + (stats.outside_swings or 0)
    total_contact = (stats.zone_contact or 0) + (stats.outside_contact or 0)
    bip = stats.balls_in_play or 0
    er = stats.earned_runs or 0
    h = stats.hits or 0
    bb = stats.walks or 0
    hr = stats.home_runs_allowed or 0

    return {
        "innings_pitched": float(ip),
        "batters_faced": float(bf),
        "strikeouts": float(stats.strikeouts or 0),
        "walks": float(bb),
        "home_runs_allowed": float(hr),
        "hits": float(h),
        "earned_runs": float(er),
        "pitches_thrown": float(stats.pitches_thrown or 0),
        # Traditional derived rates (from stored IP, H, ER, BB, HR)
        "era": (er * 9.0 / ip) if ip > 0 else 4.50,
        "whip": ((bb + h) / ip) if ip > 0 else 1.30,
        "h_per_9": (h * 9.0 / ip) if ip > 0 else 9.0,
        "hr_per_9": (hr * 9.0 / ip) if ip > 0 else 1.2,
        "k_per_9": ((stats.strikeouts or 0) * 9.0 / ip) if ip > 0 else 8.5,
        "bb_per_9": (bb * 9.0 / ip) if ip > 0 else 3.2,
        # Statcast rates
        "k_rate": (stats.strikeouts / bf) if bf > 0 else 0.22,
        "bb_rate": (bb / bf) if bf > 0 else 0.08,
        "hr_rate": (hr / bf) if bf > 0 else 0.03,
        "whiff_rate": (
            1.0 - (total_contact / total_swings) if total_swings > 0 else 0.23
        ),
        "z_contact_pct": (
            (stats.zone_contact / stats.zone_swings)
            if (stats.zone_swings or 0) > 0 else 0.84
        ),
        "chase_rate": (
            (stats.outside_swings / stats.outside_pitches)
            if (stats.outside_pitches or 0) > 0 else 0.32
        ),
        "avg_exit_velo_against": (
            (stats.total_exit_velo_against / bip) if bip > 0 else 88.0
        ),
        "hard_hit_pct_against": (
            (stats.hard_hit_against / bip) if bip > 0 else 0.35
        ),
        "barrel_pct_against": (
            (stats.barrel_against / bip) if bip > 0 else 0.07
        ),
        # Contact/power suppression for matchup compatibility
        "contact_suppression": max(-0.15, min(0.30,
            1.0 - (h / bf) - 0.30 if bf > 0 else 0.0
        )),
        "power_suppression": max(-0.30, min(0.50,
            1.0 - ((hr / bf) / 0.03) if bf > 0 else 0.0
        )),
        # Aliases for matchup.py compatibility (same values as k_rate/bb_rate)
        "strikeout_rate": (stats.strikeouts / bf) if bf > 0 else 0.22,
        "walk_rate": (bb / bf) if bf > 0 else 0.08,
    }
