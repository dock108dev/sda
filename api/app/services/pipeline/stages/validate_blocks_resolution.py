"""RESOLUTION block specificity vs final-window PBP plays."""

from __future__ import annotations

import logging
from typing import Any

from .block_types import SemanticRole
from .validate_blocks_constants import (
    _CLOCK_SPORT_FINAL_QUARTER,
    _FINAL_WINDOW_MIN_PERIOD,
)
from .validate_blocks_text import check_score_present, normalize_text

logger = logging.getLogger(__name__)


def parse_game_clock_seconds(clock: str | None) -> int | None:
    """Parse 'MM:SS' or 'SS' game-clock string to total seconds."""
    if not clock:
        return None
    clock = clock.strip()
    try:
        if ":" in clock:
            parts = clock.split(":", 1)
            return int(parts[0]) * 60 + int(parts[1])
        return int(clock)
    except (ValueError, IndexError):
        return None


def get_final_window_plays(pbp_events: list[dict[str, Any]], sport: str) -> list[dict[str, Any]]:
    """Return PBP events from the final game window for the given sport."""
    if not pbp_events:
        return []

    sport_upper = sport.upper()

    if sport_upper in _CLOCK_SPORT_FINAL_QUARTER:
        final_quarter, threshold_secs = _CLOCK_SPORT_FINAL_QUARTER[sport_upper]
        result = []
        for ev in pbp_events:
            q = ev.get("quarter", 0)
            if q > final_quarter:
                result.append(ev)
            elif q == final_quarter:
                secs = parse_game_clock_seconds(ev.get("game_clock"))
                if secs is not None and secs <= threshold_secs:
                    result.append(ev)
        return result

    if sport_upper in _FINAL_WINDOW_MIN_PERIOD:
        min_period = _FINAL_WINDOW_MIN_PERIOD[sport_upper]
        return [ev for ev in pbp_events if (ev.get("quarter") or 0) >= min_period]

    if sport_upper == "MLB":
        max_inning = max((ev.get("quarter") or 1) for ev in pbp_events)
        return [ev for ev in pbp_events if ev.get("quarter") == max_inning]

    n = max(1, len(pbp_events) // 5)
    return pbp_events[-n:]


def check_resolution_specificity(
    blocks: list[dict[str, Any]],
    pbp_events: list[dict[str, Any]],
    sport: str,
) -> tuple[list[str], list[str]]:
    """Soft check: RESOLUTION should reference a final-window play or score."""
    resolution_block: dict[str, Any] | None = None
    for block in blocks:
        if block.get("role") == SemanticRole.RESOLUTION.value:
            resolution_block = block

    if resolution_block is None:
        return [], []

    narrative = resolution_block.get("narrative", "")
    if not narrative:
        return [], []

    final_plays = get_final_window_plays(pbp_events, sport)
    if not final_plays:
        return [], []

    norm_narrative = normalize_text(narrative)

    player_names = {
        ev["player_name"].strip()
        for ev in final_plays
        if ev.get("player_name") and ev["player_name"].strip()
    }
    player_found = False
    for name in player_names:
        if len(name) <= 1:
            continue
        norm_name = normalize_text(name)
        if norm_name in norm_narrative:
            player_found = True
            break
        parts = norm_name.split()
        if len(parts) >= 2 and parts[-1] in norm_narrative:
            player_found = True
            break

    score_found = False
    if not player_found:
        for ev in final_plays:
            h = ev.get("home_score")
            a = ev.get("away_score")
            if h is not None and a is not None and (int(h) or int(a)):
                if check_score_present(narrative, int(h), int(a)):
                    score_found = True
                    break

    if player_found or score_found:
        return [], []

    block_idx = resolution_block.get("block_index", "?")
    msg = (
        f"Block {block_idx} (RESOLUTION): no traceable play reference from the "
        f"final game window (sport={sport}, window_plays={len(final_plays)}) — "
        "narrative may be generic"
    )
    logger.warning(
        "resolution_specificity_check_failed",
        extra={
            "block_index": block_idx,
            "sport": sport,
            "final_window_play_count": len(final_plays),
            "player_names_available": len(player_names),
        },
    )
    resolution_block["resolution_specificity_warning"] = True
    return [], [msg]
