"""RENDER_BLOCKS Stage Implementation.

This stage generates narrative text for each block using OpenAI.
Each block gets 1-5 sentences (~65 words) describing that stretch of play.

TWO-PASS RENDERING
==================
1. Initial render: Per-block narrative generation with role-aware prompting
2. Game-level flow pass: Single call that sees all blocks and smooths transitions

RENDERING RULES
===============
The prompt REQUIRES:
- 1-5 sentences per block (~40-100 words)
- Role-aware context (SETUP, MOMENTUM_SHIFT, etc.)
- Consequence-based narration over play enumeration
- Concrete actions and score changes
- SportsCenter-style prose describing stretches of play

The prompt FORBIDS:
- momentum, turning point, dominant, huge, clutch
- Speculation or interpretation
- References to plays not in the block
- Raw PBP artifacts (initials like "j. smith")

GAME-LEVEL FLOW PASS
====================
After initial narratives are generated, a second OpenAI call smooths
the entire game flow:
- Acknowledges time progression (early → middle → late)
- Reduces repetition across blocks
- Preserves all facts, scores, and structure
- Uses low temperature (0.2) for consistency
- If output count != input count, uses originals to preserve structure

VALIDATION
==========
Post-generation validation ensures:
- Non-empty narratives
- Word count within limits (30-120 words)
- Sentence count within limits (1-5 sentences)
- No forbidden language
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ...openai_client import get_openai_client
from ..models import StageInput, StageOutput
from .regen_context import RegenFailureContext
from .render_helpers import (
    check_overtime_mention,
    detect_overtime_info,
    inject_overtime_mention,
)
from .render_prompts import build_block_prompt, build_game_flow_pass_prompt
from .render_validation import cleanup_pbp_artifacts, validate_block_narrative

logger = logging.getLogger(__name__)


async def _apply_game_level_flow_pass(
    blocks: list[dict[str, Any]],
    game_context: dict[str, str],
    openai_client: Any,
    output: StageOutput,
    regen_context: RegenFailureContext | None = None,
) -> list[dict[str, Any]]:
    """Apply game-level flow pass to smooth transitions across blocks.

    This is a single OpenAI call that sees all blocks and rewrites narratives
    so they flow naturally as one coherent recap while preserving all facts.

    Args:
        blocks: List of block dicts with initial narratives
        game_context: Team names and context
        openai_client: OpenAI client instance
        output: StageOutput for logging
        regen_context: Optional quality-gate failure context for regen runs.

    Returns:
        Blocks with smoothed narratives (or original if pass fails)
    """
    if len(blocks) < 2:
        output.add_log("Skipping flow pass: fewer than 2 blocks")
        return blocks

    output.add_log(f"Applying game-level flow pass to {len(blocks)} blocks")

    prompt = build_game_flow_pass_prompt(blocks, game_context, regen_context=regen_context)

    try:
        # Low temperature for consistency, ~100 tokens per block
        max_tokens = 100 * len(blocks)

        response_json = await asyncio.to_thread(
            openai_client.generate,
            prompt=prompt,
            temperature=0.2,  # Low for consistency
            max_tokens=max_tokens,
        )
        response_data = json.loads(response_json)

    except json.JSONDecodeError as e:
        output.add_log(f"Flow pass returned invalid JSON, using originals: {e}", level="warning")
        return blocks

    except Exception as e:
        output.add_log(f"Flow pass failed, using originals: {e}", level="warning")
        return blocks

    # Extract revised narratives
    block_items = response_data.get("blocks", [])
    if not block_items and isinstance(response_data, list):
        block_items = response_data

    # Safety check: output count must match input count
    if len(block_items) != len(blocks):
        output.add_log(
            f"Flow pass output count mismatch ({len(block_items)} vs {len(blocks)}), using originals",
            level="warning",
        )
        return blocks

    # Build lookup by block index
    narrative_lookup: dict[int, str] = {}
    for item in block_items:
        idx = item.get("i")
        narrative = item.get("n", "")
        if idx is not None and narrative:
            narrative_lookup[idx] = narrative

    # Apply revised narratives
    revised_count = 0
    for block in blocks:
        block_idx = block["block_index"]
        if block_idx in narrative_lookup:
            new_narrative = narrative_lookup[block_idx].strip()
            if new_narrative and new_narrative != block.get("narrative", ""):
                block["narrative"] = new_narrative
                revised_count += 1

    output.add_log(f"Flow pass revised {revised_count}/{len(blocks)} block narratives")
    return blocks


async def execute_render_blocks(stage_input: StageInput) -> StageOutput:
    """Execute the RENDER_BLOCKS stage.

    Generates narrative text for each block using OpenAI.
    Each block gets 1-5 sentences (~65 words).

    Args:
        stage_input: Input containing previous_output with grouped blocks

    Returns:
        StageOutput with blocks enriched with narratives

    Raises:
        ValueError: If OpenAI not configured or prerequisites not met
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id

    output.add_log(f"Starting RENDER_BLOCKS for game {game_id}")

    # Get OpenAI client
    openai_client = get_openai_client()
    if openai_client is None:
        raise ValueError(
            "OpenAI API key not configured - cannot render block narratives. "
            "Set OPENAI_API_KEY environment variable."
        )

    # Get input data from previous stages
    previous_output = stage_input.previous_output
    if not previous_output:
        raise ValueError("RENDER_BLOCKS requires previous stage output")

    # Verify GROUP_BLOCKS completed
    blocks_grouped = previous_output.get("blocks_grouped")
    if blocks_grouped is not True:
        raise ValueError(
            f"RENDER_BLOCKS requires GROUP_BLOCKS to complete. Got blocks_grouped={blocks_grouped}"
        )

    # Get blocks and PBP data
    blocks = previous_output.get("blocks", [])
    if not blocks:
        raise ValueError("No blocks in previous stage output")

    pbp_events = previous_output.get("pbp_events", [])
    game_context = stage_input.game_context

    # Build typed regen context from game_context when this is a regen run.
    # grade_gate_failures is threaded in by PipelineExecutor._get_game_context()
    # when failure_reasons were passed to run_full_pipeline().
    regen_context: RegenFailureContext | None = None
    raw_failures: list[str] = game_context.get("grade_gate_failures", [])  # type: ignore[assignment]
    regen_attempt: int = game_context.get("regen_attempt", 0)  # type: ignore[assignment]
    if raw_failures:
        regen_context = RegenFailureContext.from_failure_reasons(
            raw_failures, regen_attempt=max(regen_attempt, 1)
        )
        output.add_log(
            f"Regen attempt {regen_attempt}: injecting {len(raw_failures)} failure dimensions into prompt"
        )

    output.add_log(f"Rendering narratives for {len(blocks)} blocks")

    # Get blowout metrics from previous stage
    is_blowout = previous_output.get("is_blowout", False)

    if is_blowout:
        output.add_log("Processing blowout game with compressed narratives")

    # Build prompt and call OpenAI; inject typed regen context into data layer.
    prompt = build_block_prompt(blocks, game_context, pbp_events, regen_context=regen_context)

    try:
        # Estimate tokens: ~200 per block for 2-4 sentences
        max_tokens = 200 * len(blocks)

        response_json = await asyncio.to_thread(
            openai_client.generate,
            prompt=prompt,
            temperature=0.5,  # Higher for more natural prose variation
            max_tokens=max_tokens,
        )
        response_data = json.loads(response_json)

    except json.JSONDecodeError as e:
        # Fail fast
        raise ValueError(f"OpenAI returned invalid JSON: {e}") from e

    except Exception as e:
        # Fail fast
        raise ValueError(f"OpenAI call failed: {e}") from e

    # Extract narratives from response
    block_items = response_data.get("blocks", [])
    if not block_items and isinstance(response_data, list):
        block_items = response_data

    output.add_log(f"Got {len(block_items)} narratives from OpenAI")

    # Build lookup by block index
    narrative_lookup: dict[int, str] = {}
    for item in block_items:
        idx = item.get("i")
        narrative = item.get("n", "")
        if idx is not None:
            narrative_lookup[idx] = narrative

    # Apply narratives to blocks with validation
    all_errors: list[str] = []
    all_warnings: list[str] = []
    total_words = 0

    for block in blocks:
        block_idx = block["block_index"]
        narrative = narrative_lookup.get(block_idx, "")

        if not narrative or not narrative.strip():
            # Fail fast
            raise ValueError(f"Block {block_idx}: No narrative from AI")

        # Clean up any raw PBP artifacts from the narrative
        narrative = cleanup_pbp_artifacts(narrative)

        # Validate
        errors, warnings = validate_block_narrative(narrative, block_idx)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

        # If hard errors, fail fast
        if errors:
            raise ValueError(f"Block {block_idx} validation failed: {errors}")

        # Check and inject overtime mention if needed
        league_code = game_context.get("sport", "NBA")
        ot_info = detect_overtime_info(block, league_code)
        if ot_info["enters_overtime"]:
            if not check_overtime_mention(narrative, ot_info, league_code):
                narrative = inject_overtime_mention(narrative, ot_info, league_code)
                output.add_log(
                    f"Block {block_idx}: Injected {ot_info['ot_label']} mention",
                    level="warning",
                )
                all_warnings.append(f"Block {block_idx}: Injected overtime mention")

        block["narrative"] = narrative
        total_words += len(narrative.split())

    output.add_log(f"Total word count: {total_words}")

    if all_warnings:
        output.add_log(f"Warnings: {len(all_warnings)}", level="warning")
        for w in all_warnings[:5]:
            output.add_log(f"  {w}", level="warning")

    # Game-level flow pass: smooth transitions across all blocks
    # This is a second OpenAI call that sees all blocks at once
    blocks = await _apply_game_level_flow_pass(
        blocks, game_context, openai_client, output, regen_context=regen_context
    )

    # Post-flow-pass: Ensure OT mentions weren't lost during flow pass
    league_code = game_context.get("sport", "NBA")
    ot_injections = 0
    for block in blocks:
        ot_info = detect_overtime_info(block, league_code)
        if ot_info["enters_overtime"]:
            narrative = block.get("narrative", "")
            if not check_overtime_mention(narrative, ot_info, league_code):
                block["narrative"] = inject_overtime_mention(narrative, ot_info, league_code)
                ot_injections += 1
                output.add_log(
                    f"Block {block['block_index']}: Re-injected {ot_info['ot_label']} mention after flow pass",
                    level="warning",
                )

    if ot_injections > 0:
        output.add_log(f"OT mentions re-injected after flow pass: {ot_injections}")

    # Recalculate total words after flow pass
    total_words = sum(len(b.get("narrative", "").split()) for b in blocks)
    output.add_log(f"Final word count after flow pass: {total_words}")

    output.add_log("RENDER_BLOCKS completed successfully")

    output.data = {
        "blocks_rendered": True,
        "blocks": blocks,
        "block_count": len(blocks),
        "total_words": total_words,
        "openai_calls": 2,  # Initial render + flow pass
        "errors": all_errors,
        "warnings": all_warnings,
        # Pass through
        "moments": previous_output.get("moments", []),
        "pbp_events": pbp_events,
        "validated": True,
        "blocks_grouped": True,
    }

    return output
