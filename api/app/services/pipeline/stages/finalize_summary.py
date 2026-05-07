"""FINALIZE_SUMMARY Stage Implementation.

Persists the v3 catch-up summary to sports_game_stories. Replaces
finalize_moments for the new pipeline.

Schema mapping (story_version="v3-summary"):
- summary_json: {summary, referenced_play_ids, key_play_ids, by_period,
                 home_final, away_final}
- ai_model_used: model name
- total_ai_calls: 1
- archetype: from CLASSIFY_GAME_SHAPE
- winner_team_id: derived from final score + team abbrevs
- version: "game-flow-v3"
- generated_at: now
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import text

from ....db.flow import SportsGameFlow
from ....db.sports import SportsGame
from ....utils.datetime_utils import now_utc
from ..models import StageInput, StageOutput

if TYPE_CHECKING:
    from ....db import AsyncSession

logger = logging.getLogger(__name__)

SUMMARY_STORY_VERSION = "v3-summary"
SUMMARY_SCHEMA_VERSION = "game-flow-v3"


def _resolve_winner_abbrev(
    game: SportsGame, home_final: int, away_final: int
) -> str | None:
    if home_final == away_final:
        return None
    home_abbr = getattr(getattr(game, "home_team", None), "abbreviation", None)
    away_abbr = getattr(getattr(game, "away_team", None), "abbreviation", None)
    return home_abbr if home_final > away_final else away_abbr


async def execute_finalize_summary(
    session: AsyncSession,
    stage_input: StageInput,
    run_uuid: str,
) -> StageOutput:
    """Persist the generated summary as a v3-summary row in sports_game_stories."""
    output = StageOutput(data={})
    game_id = stage_input.game_id
    output.add_log(f"Starting FINALIZE_SUMMARY for game {game_id}")

    previous_output = stage_input.previous_output or {}
    if not previous_output.get("summary_generated"):
        raise ValueError("FINALIZE_SUMMARY requires GENERATE_SUMMARY output")

    summary: list[str] = previous_output["summary"]
    referenced_play_ids: list[int] = previous_output.get("referenced_play_ids", [])
    key_play_ids: list[int] = previous_output.get("key_play_ids", [])
    home_final: int = int(previous_output.get("home_final") or 0)
    away_final: int = int(previous_output.get("away_final") or 0)
    by_period: list[list[int]] = [list(p) for p in previous_output.get("by_period", [])]
    archetype: str | None = previous_output.get("archetype")
    model_used: str | None = previous_output.get("model_used")
    openai_calls: int = int(previous_output.get("openai_calls") or 1)
    total_words: int = int(previous_output.get("total_words") or 0)

    game_result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
        )
        .where(SportsGame.id == game_id)
    )
    game = game_result.scalar_one_or_none()
    if not game:
        raise ValueError(f"Game {game_id} not found")
    sport = game.league.code if game.league else "NBA"
    winner_team_id = _resolve_winner_abbrev(game, home_final, away_final)

    summary_payload: dict[str, Any] = {
        "summary": summary,
        "referenced_play_ids": referenced_play_ids,
        "key_play_ids": key_play_ids,
        "home_final": home_final,
        "away_final": away_final,
        "by_period": by_period,
        "total_words": total_words,
    }

    validation_block = {
        "status": "passed",
        "warnings": [],
    }

    existing_result = await session.execute(
        select(SportsGameFlow).where(
            SportsGameFlow.game_id == game_id,
            SportsGameFlow.story_version == SUMMARY_STORY_VERSION,
        )
    )
    existing_flow = existing_result.scalar_one_or_none()

    generated_at = now_utc()

    if existing_flow:
        output.add_log(f"Updating existing v3 summary (id={existing_flow.id})")
        existing_flow.summary_json = summary_payload
        existing_flow.generated_at = generated_at
        existing_flow.ai_model_used = model_used
        existing_flow.total_ai_calls = openai_calls
        existing_flow.version = SUMMARY_SCHEMA_VERSION
        existing_flow.archetype = archetype
        existing_flow.winner_team_id = winner_team_id
        existing_flow.flow_source = "LLM"
        existing_flow.validation = validation_block
        flow_id = existing_flow.id
    else:
        output.add_log("Creating new v3 summary record")
        new_flow = SportsGameFlow(
            game_id=game_id,
            sport=sport,
            story_version=SUMMARY_STORY_VERSION,
            summary_json=summary_payload,
            generated_at=generated_at,
            ai_model_used=model_used,
            total_ai_calls=openai_calls,
            version=SUMMARY_SCHEMA_VERSION,
            archetype=archetype,
            winner_team_id=winner_team_id,
            flow_source="LLM",
            validation=validation_block,
        )
        session.add(new_flow)
        await session.flush()
        flow_id = new_flow.id

    # Best-effort realtime notification. NOTIFY failure must not roll back the row.
    try:
        notify_payload = json.dumps(
            {
                "game_id": game_id,
                "event_type": "summary_published",
                "flow_id": flow_id,
                "story_version": SUMMARY_STORY_VERSION,
            }
        )
        await session.execute(
            text("SELECT pg_notify('flow_published', :p)"), {"p": notify_payload}
        )
    except (SQLAlchemyError, OSError):
        logger.warning(
            "summary_published_notify_failed",
            extra={"game_id": game_id, "flow_id": flow_id},
            exc_info=True,
        )

    output.add_log(f"Summary persisted with id={flow_id}")
    output.data = {
        "finalized": True,
        "flow_id": flow_id,
        "game_id": game_id,
        "story_version": SUMMARY_STORY_VERSION,
        "version": SUMMARY_SCHEMA_VERSION,
        "archetype": archetype,
        "winner_team_id": winner_team_id,
        "generated_at": generated_at.isoformat(),
        "openai_calls": openai_calls,
        "total_words": total_words,
        "model_used": model_used,
    }
    return output
