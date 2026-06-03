"""Read-only helpers for pipeline execution context."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...db import AsyncSession
from ...db.pipeline import GamePipelineRun
from ...db.sports import SportsGame, SportsPlayerBoxscore
from .models import PipelineStage


async def get_game_context(session: AsyncSession, game_id: int) -> dict[str, Any]:
    """Build game context for team name resolution and player name mapping."""
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
        return {}

    # Build player name mapping from boxscores
    # Maps "D. Mitchell" -> "Donovan Mitchell"
    player_names = await build_player_name_mapping(session, game_id)

    ctx: dict[str, Any] = {
        "sport": game.league.code if game.league else "NBA",
        "home_team_name": game.home_team.name if game.home_team else "Home",
        "away_team_name": game.away_team.name if game.away_team else "Away",
        "home_team_abbrev": game.home_team.abbreviation if game.home_team else "HOME",
        "away_team_abbrev": game.away_team.abbreviation if game.away_team else "AWAY",
        "player_names": player_names,
    }
    return ctx


async def resolve_league_code(session: AsyncSession, game_id: int) -> str | None:
    """Look up the league code for a game without raising.

    Used by the structured debug logger so it can be initialized before
    any stage records data; returning None lets emission proceed even when
    the game lookup fails (the rest of the run-final logging still fires).
    """
    result = await session.execute(
        select(SportsGame)
        .options(selectinload(SportsGame.league))
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if game is None or game.league is None:
        return None
    return game.league.code


async def build_player_name_mapping(session: AsyncSession, game_id: int) -> dict[str, str]:
    """Build mapping from abbreviated names to full names.

    Maps formats like "D. Mitchell" -> "Donovan Mitchell"
    using player boxscore data.
    """
    result = await session.execute(
        select(SportsPlayerBoxscore.player_name)
        .where(SportsPlayerBoxscore.game_id == game_id)
        .where(SportsPlayerBoxscore.player_name.isnot(None))
    )
    full_names = [row[0] for row in result.fetchall()]

    mapping: dict[str, str] = {}

    # First pass: collect last names and detect duplicates
    last_name_counts: dict[str, int] = {}
    for full_name in full_names:
        if not full_name or " " not in full_name:
            continue
        parts = full_name.split()
        if len(parts) >= 2:
            last_name = parts[-1]
            last_name_counts[last_name] = last_name_counts.get(last_name, 0) + 1

    # Second pass: build mappings
    for full_name in full_names:
        if not full_name or " " not in full_name:
            continue

        parts = full_name.split()
        if len(parts) >= 2:
            # Build abbreviated form: "D. Mitchell" from "Donovan Mitchell"
            first_initial = parts[0][0].upper()
            last_name = parts[-1]
            abbrev = f"{first_initial}. {last_name}"
            mapping[abbrev] = full_name

            # Only map last name alone if it's unique in this game
            # (e.g., skip "Green" if both "Jalen Green" and "Draymond Green" play)
            if last_name_counts.get(last_name, 0) == 1:
                mapping[last_name] = full_name

    return mapping


def accumulate_outputs(
    run: GamePipelineRun,
    up_to_stage: PipelineStage,
) -> dict[str, Any]:
    """Accumulate outputs from all completed stages up to the given stage.

    Each stage builds on the outputs of previous stages.
    """
    accumulated: dict[str, Any] = {}

    for stage in PipelineStage.ordered_stages():
        if stage == up_to_stage:
            break

        # Find stage record
        stage_record = next(
            (s for s in run.stages if s.stage == stage.value),
            None,
        )

        if stage_record and stage_record.output_json:
            # Merge stage output into accumulated
            accumulated.update(stage_record.output_json)

    return accumulated
