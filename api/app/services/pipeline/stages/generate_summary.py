"""GENERATE_SUMMARY Stage Implementation.

The single LLM-touching stage in the catch-up summary pipeline. Takes the
deterministic outputs of NORMALIZE_PBP and CLASSIFY_GAME_SHAPE, picks the
narratively important plays, and asks gpt-4o-mini for a 3-5 paragraph
recap in one call.

Replaces the prior 2-call render_blocks + flow-pass pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from ...openai_client import get_openai_client
from ..models import StageInput, StageOutput
from .select_key_plays import select_key_plays_full_game
from .summary_prompt import (
    SYSTEM_PROMPT,
    build_summary_prompt,
    parse_summary_response,
)

logger = logging.getLogger(__name__)

_MODEL_TEMPERATURE = 0.5
_MAX_TOKENS = 1200


def _final_score(pbp_events: list[dict[str, Any]]) -> tuple[int, int]:
    """Final cumulative score read from the last play.

    NORMALIZE_PBP enforces score continuity, so the last play's score is
    authoritative for what the LLM should narrate.
    """
    if not pbp_events:
        return 0, 0
    last = pbp_events[-1]
    return int(last.get("home_score") or 0), int(last.get("away_score") or 0)


def _by_period(pbp_events: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Per-period (home, away) points scored. Order matches play order."""
    if not pbp_events:
        return []
    by_period: dict[int, tuple[int, int]] = {}
    last_h = 0
    last_a = 0
    last_period = 0
    period_start_h = 0
    period_start_a = 0
    for ev in pbp_events:
        period = ev.get("quarter") or ev.get("period") or 1
        if period != last_period:
            if last_period > 0:
                by_period[last_period] = (
                    last_h - period_start_h,
                    last_a - period_start_a,
                )
            period_start_h = last_h
            period_start_a = last_a
            last_period = period
        last_h = ev.get("home_score") or last_h
        last_a = ev.get("away_score") or last_a
    if last_period > 0:
        by_period[last_period] = (
            last_h - period_start_h,
            last_a - period_start_a,
        )
    return [by_period[p] for p in sorted(by_period)]


def _enrich_key_plays(
    play_ids: list[int],
    pbp_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pull the full play record for each selected id, in chronological order."""
    by_id = {ev.get("play_index"): ev for ev in pbp_events if "play_index" in ev}
    return [by_id[pid] for pid in play_ids if pid in by_id]


async def execute_generate_summary(stage_input: StageInput) -> StageOutput:
    """Generate the catch-up summary in one LLM call.

    Reads pbp_events + archetype from the accumulated previous-stage output,
    selects key plays, builds the consolidated prompt, calls OpenAI once,
    and returns the summary paragraphs + referenced play ids.
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id
    output.add_log(f"Starting GENERATE_SUMMARY for game {game_id}")

    previous_output = stage_input.previous_output or {}
    pbp_events = previous_output.get("pbp_events") or []
    if not pbp_events:
        raise ValueError("GENERATE_SUMMARY requires pbp_events from NORMALIZE_PBP")

    archetype = previous_output.get("archetype")
    ctx = stage_input.game_context or {}
    league_code = ctx.get("sport", "NBA")
    home_team = ctx.get("home_team_name", "Home")
    away_team = ctx.get("away_team_name", "Away")
    home_abbrev = ctx.get("home_team_abbrev", "HOME")
    away_abbrev = ctx.get("away_team_abbrev", "AWAY")

    key_play_ids = select_key_plays_full_game(pbp_events, league_code=league_code)
    output.add_log(f"Selected {len(key_play_ids)} key plays: {key_play_ids}")
    enriched_plays = _enrich_key_plays(key_play_ids, pbp_events)

    home_final, away_final = _final_score(pbp_events)
    by_period = _by_period(pbp_events)

    prompt = build_summary_prompt(
        league_code=league_code,
        home_team=home_team,
        away_team=away_team,
        home_abbrev=home_abbrev,
        away_abbrev=away_abbrev,
        home_final=home_final,
        away_final=away_final,
        archetype=archetype,
        key_plays=enriched_plays,
        by_period=by_period,
    )

    client = get_openai_client()
    if client is None:
        raise RuntimeError(
            "OpenAI client unavailable — set openai_api_key in settings"
        )

    output.add_log(f"Calling OpenAI model={client.model}")
    raw = client.generate(
        prompt=prompt,
        temperature=_MODEL_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
        max_retries=3,
        system_prompt=SYSTEM_PROMPT,
    )

    parsed = parse_summary_response(raw)
    summary_paragraphs: list[str] = parsed["summary"]
    referenced_ids: list[int] = parsed["referenced_play_ids"]

    # Constrain referenced ids to plays we actually offered the model. The
    # prompt asks the model to pick from the key plays list, but if it
    # hallucinated an id we drop it rather than serving it to clients.
    valid_ids = set(key_play_ids)
    referenced_ids = [pid for pid in referenced_ids if pid in valid_ids]

    total_words = sum(len(p.split()) for p in summary_paragraphs)
    output.add_log(
        f"Summary generated: {len(summary_paragraphs)} paragraphs, "
        f"{total_words} words, {len(referenced_ids)} referenced plays"
    )

    output.data = {
        "summary_generated": True,
        "summary": summary_paragraphs,
        "referenced_play_ids": referenced_ids,
        "key_play_ids": key_play_ids,
        "home_final": home_final,
        "away_final": away_final,
        "by_period": by_period,
        "openai_calls": 1,
        "total_words": total_words,
        "model_used": client.model,
        # Pass-through for FINALIZE_SUMMARY:
        "archetype": archetype,
        "pbp_events": pbp_events,
    }
    return output
