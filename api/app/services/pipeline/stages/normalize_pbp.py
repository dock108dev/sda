"""NORMALIZE_PBP Stage Implementation.

This stage reads raw play-by-play data from the database and produces
normalized events with phase assignments and synthetic timestamps.

Input: game_id (reads from sports_game_plays table)
Output: NormalizedPBPOutput with pbp_events, phase_boundaries, etc.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ....db import AsyncSession
from ....db.resolution import PBPSnapshot
from ....db.sports import SportsGame, SportsGamePlay
from ....services.resolution_tracker import ResolutionTracker
from ..models import NormalizedPBPOutput, StageInput, StageOutput
from .normalize_pbp_helpers import (
    build_pbp_events,
    compute_resolution_stats,
)
from .phase_boundaries import (
    compute_mlb_phase_boundaries,
    compute_ncaab_phase_boundaries,
    compute_nhl_phase_boundaries,
    compute_phase_boundaries,
    mlb_game_end,
    nba_game_end,
    ncaab_game_end,
    nhl_game_end,
)

logger = logging.getLogger(__name__)


async def execute_normalize_pbp(
    session: AsyncSession,
    stage_input: StageInput,
    pipeline_run_id: int | None = None,
) -> StageOutput:
    """Execute the NORMALIZE_PBP stage.

    Reads play-by-play data from the database and produces normalized
    events with phase assignments and synthetic timestamps.

    Also creates a PBP snapshot for auditability.

    Args:
        session: Database session
        stage_input: Input containing game_id
        pipeline_run_id: Optional pipeline run ID for snapshot association

    Returns:
        StageOutput with NormalizedPBPOutput data
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id
    run_id = pipeline_run_id or stage_input.run_id

    output.add_log(f"Starting NORMALIZE_PBP for game {game_id}")

    # Fetch game with relations
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()

    if not game:
        raise ValueError(f"Game {game_id} not found")

    if not game.is_final:
        raise ValueError(f"Game {game_id} is not final (status: {game.status})")

    # Get league code for sport-specific handling
    league_code = game.league.code if game.league else "NBA"
    output.add_log(f"Game found: {game.away_team.name} @ {game.home_team.name} ({league_code})")

    # Fetch plays with team relationship
    plays_result = await session.execute(
        select(SportsGamePlay)
        .options(selectinload(SportsGamePlay.team))
        .where(SportsGamePlay.game_id == game_id)
        .order_by(SportsGamePlay.play_index)
    )
    plays = list(plays_result.scalars().all())

    if not plays:
        raise ValueError(f"Game {game_id} has no play-by-play data")

    output.add_log(f"Found {len(plays)} plays")

    # Compute resolution stats BEFORE normalization
    resolution_stats = compute_resolution_stats(plays)
    output.add_log(f"Team resolution rate: {resolution_stats['team_resolution_rate']}%")

    if resolution_stats["teams_unresolved"] > 0:
        output.add_log(
            f"WARNING: {resolution_stats['teams_unresolved']} plays have unresolved teams",
            "warning",
        )

    # Track entity resolutions for auditability
    resolution_tracker = ResolutionTracker(game_id, run_id)

    # Build team context from game
    home_abbrev = game.home_team.abbreviation if game.home_team else None
    away_abbrev = game.away_team.abbreviation if game.away_team else None

    # Track team and player resolutions
    for play in plays:
        # Track team resolution
        raw_team = play.raw_data.get("teamTricode") or play.raw_data.get("team")
        if raw_team:
            if play.team_id is not None:
                resolution_tracker.track_team(
                    source_abbrev=raw_team,
                    resolved_id=play.team_id,
                    resolved_name=play.team.name if play.team else None,
                    method="game_context"
                    if raw_team.upper() in (home_abbrev, away_abbrev)
                    else "abbreviation_lookup",
                    play_index=play.play_index,
                    source_context={"raw_data": play.raw_data},
                )
            else:
                resolution_tracker.track_team_failure(
                    source_abbrev=raw_team,
                    reason="No matching team found for abbreviation",
                    play_index=play.play_index,
                    source_context={"raw_data": play.raw_data},
                )

        # Track player resolution (name normalization)
        if play.player_name:
            resolution_tracker.track_player(
                source_name=play.player_name,
                resolved_name=play.player_name,
                method="passthrough",
                play_index=play.play_index,
            )

    # Get resolution summary for logging
    res_summary = resolution_tracker.get_summary()
    output.add_log(
        f"Resolution tracking: {res_summary.teams_resolved}/{res_summary.teams_total} teams, "
        f"{res_summary.players_resolved}/{res_summary.players_total} players"
    )

    # Persist entity resolutions
    try:
        resolution_count = await resolution_tracker.persist(session)
        output.add_log(f"Persisted {resolution_count} entity resolutions")
    except Exception as e:
        output.add_log(f"Warning: Failed to persist entity resolutions: {e}", "warning")

    # Compute game timing (league-specific)
    game_start = game.start_time
    is_ncaab = league_code == "NCAAB"
    is_nhl = league_code == "NHL"
    is_mlb = league_code == "MLB"

    if is_mlb:
        regulation_periods = 9
    elif is_nhl:
        regulation_periods = 3
    elif is_ncaab:
        regulation_periods = 2
    else:
        regulation_periods = 4

    if is_mlb:
        game_end = mlb_game_end(game_start, plays)
    elif is_nhl:
        game_end = nhl_game_end(game_start, plays)
    elif is_ncaab:
        game_end = ncaab_game_end(game_start, plays)
    else:
        game_end = nba_game_end(game_start, plays)

    has_overtime = any((play.quarter or 0) > regulation_periods for play in plays)

    output.add_log(f"Game timing: {game_start.isoformat()} to {game_end.isoformat()}")
    if has_overtime:
        output.add_log("Game went to overtime")

    # Build normalized PBP events with score continuity enforcement
    pbp_events, score_violations = build_pbp_events(
        plays, game_start, game_id, league_code=league_code
    )

    output.add_log(f"Normalized {len(pbp_events)} PBP events")

    # Log score violations if any were detected
    if score_violations:
        output.add_log(
            f"SCORE CONTINUITY: Corrected {len(score_violations)} score violations",
            "warning",
        )
        for violation in score_violations[:5]:  # Log first 5 for visibility
            output.add_log(
                f"  {violation['type']}: period {violation.get('period')}, "
                f"play {violation.get('play_index')}: {violation.get('message', '')}",
                "warning",
            )
        if len(score_violations) > 5:
            output.add_log(
                f"  ... and {len(score_violations) - 5} more violations",
                "warning",
            )

    # Compute phase boundaries for later use (league-specific)
    if is_mlb:
        max_inning = max((play.quarter or 0) for play in plays)
        extra_innings = max(0, max_inning - 9)
        phase_boundaries = compute_mlb_phase_boundaries(
            game_start, has_overtime, extra_innings
        )
    elif is_nhl:
        # Check for shootout (period 5)
        has_shootout = any((play.quarter or 0) == 5 for play in plays)
        phase_boundaries = compute_nhl_phase_boundaries(
            game_start, has_overtime, has_shootout
        )
    elif is_ncaab:
        phase_boundaries = compute_ncaab_phase_boundaries(game_start, has_overtime)
    else:
        phase_boundaries = compute_phase_boundaries(game_start, has_overtime)

    # Convert datetime boundaries to ISO strings for JSON serialization
    phase_boundaries_str = {
        phase: (start.isoformat(), end.isoformat())
        for phase, (start, end) in phase_boundaries.items()
    }

    # Create PBP snapshot for auditability
    try:
        snapshot = PBPSnapshot(
            game_id=game_id,
            pipeline_run_id=run_id,
            snapshot_type="normalized",
            source="pipeline",
            play_count=len(pbp_events),
            plays_json=pbp_events,
            metadata_json={
                "game_start": game_start.isoformat(),
                "game_end": game_end.isoformat(),
                "has_overtime": has_overtime,
                "phase_boundaries": phase_boundaries_str,
                "home_team": game.home_team.name if game.home_team else None,
                "away_team": game.away_team.name if game.away_team else None,
                "league_code": league_code,
            },
            resolution_stats=resolution_stats,
        )
        session.add(snapshot)
        await session.flush()
        output.add_log(f"Created PBP snapshot (id={snapshot.id})")
    except Exception as e:
        output.add_log(f"Warning: Failed to create PBP snapshot: {e}", "warning")

    # Build output
    normalized_output = NormalizedPBPOutput(
        pbp_events=pbp_events,
        game_start=game_start.isoformat(),
        game_end=game_end.isoformat(),
        has_overtime=has_overtime,
        total_plays=len(plays),
        phase_boundaries=phase_boundaries_str,
    )

    # Add resolution stats and score violations to output for visibility
    output.data = {
        **normalized_output.to_dict(),
        "resolution_stats": resolution_stats,
        "score_violations": score_violations,
        "score_violations_count": len(score_violations),
    }
    output.add_log("NORMALIZE_PBP completed successfully")

    return output
