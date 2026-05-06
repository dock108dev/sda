"""Prompt building for RENDER_BLOCKS stage.

Archetype-aware, evidence-grounded prompts for narrative block generation.
Per BRAINDUMP §Narrative generation rules:

- 1-2 sentences per block, 25-55 words
- Every block must explain why that segment mattered
- No unsupported claims about rhythm/energy/composure/tactics/effort/intent
- No generic sports phrases; banned-phrase list injected per-call
- Structured per-segment evidence — never an undifferentiated play list

Pure presentation helpers (period labels, contributors lines, game-winning play
detection) live in ``render_prompt_helpers``.
"""

from __future__ import annotations

import re
from typing import Any

from ..helpers.evidence_selection import SegmentEvidence
from .regen_context import RegenFailureContext
from .render_helpers import detect_overtime_info
from .render_prompt_helpers import (
    _build_period_label,
    _format_contributors_line,
    detect_game_winning_play,
)
from .render_validation import BANNED_PHRASES, SPECULATION_PATTERNS

# Player/team strings reach this prompt straight from PBP/boxscore ingestion
# and (in NHL/NCAAB) from third-party feed JSON. Strip ASCII control bytes,
# CR/LF/tab, and the markdown/JSON characters that could break the structured
# prompt sections or be (mis)interpreted as instructions by the model. Length
# is bounded to keep a single odd row from blowing the prompt budget.
_PROMPT_STRING_MAX_LEN = 80
_PROMPT_STRING_STRIP_RE = re.compile(r"[\x00-\x1f\x7f`{}\[\]\"]")


def _sanitize_prompt_string(value: str | None, *, default: str = "") -> str:
    """Strip prompt-breaking characters and bound the length of an LLM input.

    Defense-in-depth against malformed names from upstream feeds — not a
    replacement for upstream validation. Preserves typical name punctuation
    (apostrophes, hyphens, periods, accents) so legitimate names render
    correctly.
    """
    if not value:
        return default
    cleaned = _PROMPT_STRING_STRIP_RE.sub("", str(value)).strip()
    if not cleaned:
        return default
    if len(cleaned) > _PROMPT_STRING_MAX_LEN:
        cleaned = cleaned[:_PROMPT_STRING_MAX_LEN]
    return cleaned

# System prompt — verbatim from BRAINDUMP §Prompt rules.
SYSTEM_PROMPT_TEMPLATE = (
    "Write Scroll Down Sports Game Flow blocks. You are not writing a generic "
    "recap. You are explaining the shape of the game. Use only the supplied "
    "game shape, segment evidence, score movement, and player stats. Every "
    "block must explain why that segment mattered. Avoid unsupported claims "
    "about rhythm, energy, composure, tactics, confidence, effort, or intent. "
    "Avoid generic sports phrases. If the game was already decided, say so "
    "plainly. If a segment was low leverage, compress it. Return strict JSON only."
)

WORD_COUNT_RULE = "Each block: 25-55 words, 1-2 sentences."


# ---------------------------------------------------------------------------
# Archetype-specific guidance
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Story-role-specific guidance (v3 contract)
# ---------------------------------------------------------------------------


def _story_role_guidance(story_role: str | None, league_code: str) -> list[str]:
    """Return prompt lines tailored to the block's narrative beat.

    The brief calls for each block to have one clear reason to exist; the
    story_role tag (set by Pass 2's classifier) tells the writer which beat
    this block represents. Sport-specific examples sharpen the guidance —
    a "first_separation" reads differently for MLB (HR / multi-run inning)
    vs NBA (8-0 run / first double-digit lead).
    """
    if not story_role:
        return []
    code = (league_code or "NBA").upper()

    lines: list[str] = [f"BEAT: {story_role}"]
    if story_role == "opening":
        lines.append(
            "- Set the score state and tempo plainly. Do NOT call out the "
            "first major run, lead change, or eventual outcome — those belong "
            "to later blocks. 1 sentence is fine if there is little to say."
        )
    elif story_role == "first_separation":
        if code == "MLB":
            lines.append(
                "- Name the player and event that opened the gap (HR, multi-run "
                "inning). State the resulting score. Do not yet describe the "
                "rout — only the moment the lead first became real."
            )
        elif code == "NHL":
            lines.append(
                "- Name the goal-scorer and assistants if available, the period "
                "and clock window, and the resulting lead. Do not pre-narrate "
                "the closing stretch."
            )
        else:
            lines.append(
                "- Name the player or run that created the first meaningful "
                "lead and the resulting score. Avoid foreshadowing later beats."
            )
    elif story_role == "response":
        lines.append(
            "- The previous block established a beat; this block is the "
            "trailing team's answer or a stabilizing stretch. Quantify the "
            "response (run size, runs/goals scored, margin restored). Do not "
            "frame it as 'kept pace' or 'kept it close' without a number."
        )
    elif story_role == "lead_change":
        lines.append(
            "- The lead flipped inside this block. Name the play, the player, "
            "and the score the moment the lead changed. The lead change is "
            "the entire reason this block exists — lead with it."
        )
    elif story_role == "turning_point":
        lines.append(
            "- This is the segment that decided the outcome. Name the run, "
            "the player who powered it, and the resulting margin. Do not "
            "soften with 'pivotal' or 'high-leverage' — show the swing."
        )
    elif story_role == "closeout":
        if code == "MLB":
            lines.append(
                "- Final innings — describe what closed the game. If the lead "
                "was already secure, say so plainly and report the final. "
                "If the trailing team's last threat fizzled, name how. Do not "
                "manufacture suspense; do not report stats that did not happen "
                "in this block."
            )
        elif code == "NHL":
            lines.append(
                "- Final period or OT — describe the deciding goal and any "
                "empty-net cosmetics. If an OT/SO decided it, name the "
                "scorer and that the game went past regulation."
            )
        else:
            lines.append(
                "- Closing stretch — describe the possessions that decided "
                "the game (final lead change, game-sealing shot, late stops). "
                "If the result was already decided, say so plainly."
            )
    elif story_role == "blowout_compression":
        lines.append(
            "- The middle of a blowout. Compress: name the score arc only "
            "(e.g. 'middle innings turned the lead into a rout' / 'San Antonio "
            "extended the gap through the third'). Do NOT narrate "
            "possession-by-possession. Do NOT pretend any of this stretch "
            "was in doubt. 1 sentence is enough."
        )
    return lines


def _format_featured_players_section(
    featured: list[dict[str, Any]] | None,
) -> list[str]:
    """Render v3 ``featured_players`` as causal anchors for the prompt.

    Lines look like:
        Anchor: Aaron Judge (NYY) — opened the scoring with 1 run …
    The model is told to honor these mentions when they fit the beat —
    they are not optional decoration.
    """
    if not featured:
        return []
    out: list[str] = ["Anchors (must explain the beat, not decorate):"]
    for fp in featured:
        name = _sanitize_prompt_string(fp.get("name"), default="player")
        team = fp.get("team")
        team_label = f" ({team})" if team else ""
        reason = _sanitize_prompt_string(fp.get("reason"), default="").strip()
        if not reason:
            continue
        out.append(f"- {name}{team_label} — {reason}")
    if len(out) == 1:
        return []
    return out


def _archetype_guidance(archetype: str | None) -> list[str]:
    """Return prompt lines describing what the archetype demands of the narrative.

    Each archetype gets concrete framing the writer must respect. Unknown
    archetypes return no additional guidance — the system prompt's general
    rules still apply.
    """
    if not archetype:
        return []

    lines: list[str] = [f"GAME SHAPE: {archetype}"]
    if archetype in {"blowout", "early_avalanche_blowout"}:
        lines += [
            "- The game was decided early. Late blocks must compress: name the "
            "final margin, do not narrate possession-by-possession action that "
            "didn't change the outcome.",
            "- Do not describe trailing-team scoring after the result is set as "
            "a 'rally', 'surge', or 'response'.",
        ]
        if archetype == "early_avalanche_blowout":
            lines.append(
                "- Frame the early scoring outburst explicitly; the rest of the "
                "game is denouement."
            )
    elif archetype == "comeback":
        lines += [
            "- The eventual winner trailed by a meaningful margin. Name the "
            "deficit they faced and the swing moment that erased it.",
            "- Do not bury the deficit — quantify it (e.g., 'down 14') and "
            "describe what flipped.",
        ]
    elif archetype == "fake_close":
        lines += [
            "- The final margin is close, but one team controlled most of the "
            "game by a wide margin. Do not describe this as a back-and-forth "
            "contest — narrate the wide stretch and the late tightening.",
        ]
    elif archetype == "late_separation":
        lines += [
            "- The score was within one possession entering the final period, "
            "then separated. Treat the separation as the decisive moment; "
            "earlier blocks describe the close stretch.",
        ]
    elif archetype == "back_and_forth":
        lines += [
            "- Multiple lead changes. Honor the swings — do not flatten the "
            "game into a single team's narrative.",
        ]
    elif archetype == "wire_to_wire":
        lines += [
            "- The eventual winner led from the first score and the lead never "
            "flipped (overall game shape — for your context only). Do NOT "
            "translate this directly into early-block prose. Each block "
            "describes only its own scope; reserve full-game framing for the "
            "FINAL block.",
            "- Do not invent suspense or describe the trailing team as a "
            "real threat unless evidence supports it.",
        ]
    elif archetype == "low_event":
        lines += [
            "- Low-scoring or one-sided shutout. Compress; describe the "
            "quietness of the game directly. Do not manufacture drama from "
            "scoreless stretches.",
        ]
    return lines


# ---------------------------------------------------------------------------
# Evidence formatting
# ---------------------------------------------------------------------------


def _format_evidence_block(
    evidence: SegmentEvidence | None,
    league_code: str,
    home_team: str,
    away_team: str,
) -> list[str]:
    """Render a SegmentEvidence as compact prompt lines.

    Returns one or more `Evidence:` lines describing scoring plays, lead
    changes, scoring runs, leverage, and special markers. Returns an empty
    list when there is nothing to say (caller decides whether to skip).
    """
    if evidence is None:
        return []

    lines: list[str] = [f"Leverage: {evidence.leverage}"]

    if evidence.scoring_plays:
        scoring_pts = sum(
            (sp.score_after[0] - sp.score_before[0])
            + (sp.score_after[1] - sp.score_before[1])
            for sp in evidence.scoring_plays
        )
        lines.append(
            f"Scoring plays: {len(evidence.scoring_plays)} ({scoring_pts} total points/runs/goals)"
        )
    else:
        lines.append("Scoring plays: none in this segment")

    if evidence.lead_changes:
        lines.append(f"Lead changes: {len(evidence.lead_changes)}")

    for run in evidence.scoring_runs:
        team_label = _resolve_team_label(run.team, home_team, away_team)
        unit = _scoring_unit(league_code)
        lines.append(
            f"Scoring run: {team_label} +{run.points} {unit} over {run.duration_plays} plays"
        )

    if evidence.featured_players:
        parts = []
        for fp in evidence.featured_players:
            team_label = _resolve_team_label(fp.team, home_team, away_team)
            safe_name = _sanitize_prompt_string(fp.name, default="player")
            parts.append(f"{safe_name} ({team_label}) +{fp.delta_contribution}")
        lines.append("Featured players: " + ", ".join(parts))

    markers: list[str] = []
    if evidence.is_overtime:
        markers.append("overtime")
    if evidence.is_power_play_goal:
        markers.append("power-play goal")
    if evidence.is_short_handed_goal:
        markers.append("short-handed goal")
    if evidence.is_empty_net:
        markers.append("empty-net goal")
    if any(sp.is_home_run for sp in evidence.scoring_plays):
        markers.append("home run")
    if markers:
        lines.append("Markers: " + ", ".join(markers))

    if (league_code or "").upper() == "NHL" and evidence.is_empty_net:
        lines.append(
            "Note: empty-net goal changed the displayed final margin; the "
            "deciding goal happened earlier."
        )

    return lines


def _resolve_team_label(team: str | None, home_team: str, away_team: str) -> str:
    """Map an evidence team token (HOME/AWAY/abbrev) to a readable name."""
    if not team:
        return "team"
    upper = team.upper()
    if upper == "HOME":
        return home_team
    if upper == "AWAY":
        return away_team
    return team


def _scoring_unit(league_code: str) -> str:
    code = (league_code or "NBA").upper()
    if code == "MLB":
        return "runs"
    if code == "NHL":
        return "goals"
    return "pts"


def _nhl_context_lines(
    blocks: list[dict[str, Any]],
    game_context: dict[str, Any],
) -> list[str]:
    """Render the NHL-specific prompt section.

    Surfaces hockey-only narrative cues the writer should respect: empty-net
    goals' effect on the final margin, OT/shootout treatment, and an optional
    ``shots_by_period`` line when the caller threaded shot totals through
    ``game_context``.
    """
    out: list[str] = ["", "NHL CONTEXT:"]
    out.append(
        "- Goals drive the narrative. Name who scored and when the lead "
        "shifted; do not narrate every shift or stoppage."
    )
    out.append(
        "- An empty-net goal changes the displayed final margin but is not the "
        "deciding goal; describe the deciding goal first."
    )

    has_any_ot_block = any(
        detect_overtime_info(block, "NHL")["has_overtime"] for block in blocks
    )
    if has_any_ot_block:
        out.append(
            "- Overtime / shootout gets its own dedicated block — the segment "
            "ends in regulation tied and the OT/SO outcome decides the game."
        )

    shots_by_period = game_context.get("shots_by_period") if game_context else None
    shots_line = _format_shots_by_period(shots_by_period)
    if shots_line:
        out.append(shots_line)

    return out


def _format_shots_by_period(shots_by_period: Any) -> str:
    """Render the supplied shot totals as a single supporting-evidence line.

    Accepts either a list/tuple of (home, away) pairs or a list of dicts with
    home/away keys. Returns an empty string when the input is missing or
    malformed — shots_by_period is supplementary context, never required.
    """
    if not shots_by_period:
        return ""
    parts: list[str] = []
    try:
        for i, item in enumerate(shots_by_period, start=1):
            if isinstance(item, dict):
                home = item.get("home")
                away = item.get("away")
            else:
                home, away = item[0], item[1]
            if home is None or away is None:
                continue
            parts.append(f"P{i} {int(home)}-{int(away)}")
    except (TypeError, ValueError, IndexError, KeyError):
        return ""
    if not parts:
        return ""
    return "- Shots by period (supporting evidence, not required): " + ", ".join(parts)


def _format_banned_phrases() -> str:
    """Render the hard-banned phrase list as a single comma-joined string.

    Combines BANNED_PHRASES (hard-failing) and SPECULATION_PATTERNS (regen
    feedback) — both are forbidden in output and the model should treat them
    identically when generating.
    """
    combined = sorted(set(BANNED_PHRASES) | set(SPECULATION_PATTERNS))
    return ", ".join(f'"{p}"' for p in combined)


# ---------------------------------------------------------------------------
# Block prompt
# ---------------------------------------------------------------------------


def build_block_prompt(
    blocks: list[dict[str, Any]],
    game_context: dict[str, str],
    pbp_events: list[dict[str, Any]],
    *,
    archetype: str | None = None,
    evidence_by_block: dict[int, SegmentEvidence] | None = None,
    regen_context: RegenFailureContext | None = None,
) -> str:
    """Build the per-block render prompt.

    Args:
        blocks: List of block dicts (without narratives).
        game_context: Team names and league code.
        pbp_events: Normalized PBP events; used only for player roster
            extraction and game-winning-play detection on RESOLUTION blocks.
            The undifferentiated play list is *not* fed to the model.
        archetype: Game-shape archetype from CLASSIFY_GAME_SHAPE. Drives
            archetype-specific narrative guidance.
        evidence_by_block: Mapping of ``block_index`` → SegmentEvidence
            (from the evidence_selection helper). Provides the structured
            per-segment payload that replaces raw play lists.
        regen_context: Optional quality-gate failure context for regen runs.

    Returns:
        The complete prompt string for the per-block OpenAI call.
    """
    home_team = _sanitize_prompt_string(
        game_context.get("home_team_name"), default="Home"
    )
    away_team = _sanitize_prompt_string(
        game_context.get("away_team_name"), default="Away"
    )
    home_abbrev = _sanitize_prompt_string(game_context.get("home_team_abbrev"))
    away_abbrev = _sanitize_prompt_string(game_context.get("away_team_abbrev"))
    league_code = game_context.get("sport", "NBA")
    evidence_by_block = evidence_by_block or {}

    has_any_overtime = any(
        detect_overtime_info(block, league_code)["has_overtime"]
        for block in blocks
    )

    home_players, away_players = _collect_rosters(
        pbp_events, home_abbrev, away_abbrev
    )

    parts: list[str] = [SYSTEM_PROMPT_TEMPLATE, "", WORD_COUNT_RULE, ""]
    parts.append(f"Teams: {away_team} (away) vs {home_team} (home)")

    parts.extend(_archetype_guidance(archetype))

    if home_players or away_players:
        parts.append("")
        parts.append("ROSTERS:")
        if home_players:
            parts.append(
                f"{home_team} (home): {', '.join(sorted(home_players)[:10])}"
            )
        if away_players:
            parts.append(
                f"{away_team} (away): {', '.join(sorted(away_players)[:10])}"
            )

    parts.extend([
        "",
        "BANNED PHRASES (do not use any of these, in any tense or variation):",
        _format_banned_phrases(),
        "",
        "STYLE:",
        "- Full team name on first mention; short name or pronoun thereafter.",
        "- Player full name on first mention across the flow; last name after.",
        "- No 'X had Y points' stat-feed prose. Describe actions and effects.",
        "- No subjective adjectives (incredible, amazing, dominant, clutch, etc.).",
        "- No foreshadowing in early blocks; do not 'would-be' or 'would prove'.",
        "- BLOCK SCOPE: each block describes ONLY events within its period "
        "range. Do not summarize the rest of the game from an early-block "
        "viewpoint. Phrases like 'throughout the game', 'never allowed "
        "[opponent] to overtake', 'maintained the lead the whole way', "
        "'wire-to-wire' are reserved for the FINAL block, and only when the "
        "block-end margin actually decides the game (a 1-run / one-possession "
        "lead is NOT decided — preserve the suspense the score itself implies).",
    ])

    if has_any_overtime:
        parts.extend([
            "",
            "OVERTIME (CRITICAL):",
            "- When a block transitions into overtime/extra innings/shootout, "
            "the narrative MUST explicitly mention it.",
        ])

    if (league_code or "").upper() == "NHL":
        parts.extend(_nhl_context_lines(blocks, game_context))

    if regen_context is not None and regen_context.has_failures():
        parts.extend(["", regen_context.render_for_prompt()])

    parts.extend([
        "",
        'Return JSON: {"blocks": [{"i": block_index, "n": "narrative"}]}',
        "",
        "BLOCKS:",
    ])

    for block in blocks:
        parts.extend(
            _format_block_section(
                block,
                evidence_by_block.get(block["block_index"]),
                pbp_events,
                game_context,
                archetype,
            )
        )

    return "\n".join(parts)


def _collect_rosters(
    pbp_events: list[dict[str, Any]],
    home_abbrev: str,
    away_abbrev: str,
) -> tuple[set[str], set[str]]:
    home_players: set[str] = set()
    away_players: set[str] = set()
    if not (home_abbrev or away_abbrev):
        return home_players, away_players
    home_up = home_abbrev.upper()
    away_up = away_abbrev.upper()
    for evt in pbp_events:
        # Sanitize before insertion so the prompt is never asked to carry an
        # adversarially-shaped player_name from upstream feed data.
        name = _sanitize_prompt_string(evt.get("player_name"))
        evt_abbrev = (evt.get("team_abbreviation") or "").upper()
        if not name or not evt_abbrev:
            continue
        if home_up and evt_abbrev == home_up:
            home_players.add(name)
        elif away_up and evt_abbrev == away_up:
            away_players.add(name)
    return home_players, away_players


def _format_block_section(
    block: dict[str, Any],
    evidence: SegmentEvidence | None,
    pbp_events: list[dict[str, Any]],
    game_context: dict[str, str],
    archetype: str | None,
) -> list[str]:
    home_team = game_context.get("home_team_name", "Home")
    away_team = game_context.get("away_team_name", "Away")
    league_code = game_context.get("sport", "NBA")

    block_idx = block["block_index"]
    role = block["role"]
    score_before = block["score_before"]
    score_after = block["score_after"]
    period_start = block.get("period_start", 1)
    period_end = block.get("period_end", period_start)

    period_label = _build_period_label(league_code, period_start, period_end)
    ot_info = detect_overtime_info(block, league_code)

    section: list[str] = [
        f"\nBlock {block_idx} ({role}, {period_label}):",
        (
            f"Score: {away_team} {score_before[1]}-{score_before[0]} {home_team} "
            f"-> {away_team} {score_after[1]}-{score_after[0]} {home_team}"
        ),
    ]

    if ot_info["enters_overtime"]:
        section.append(
            f"*** ENTERS {ot_info['ot_label'].upper()} — narrative MUST mention "
            f"going to {ot_info['ot_label']} ***"
        )
    elif ot_info["has_overtime"] and not ot_info["enters_overtime"]:
        section.append(f"(In {ot_info['ot_label']})")

    # v3: per-block beat guidance + causal player anchors. Both come from
    # GROUP_BLOCKS' classifier (story_role) and RENDER_BLOCKS' featured-
    # player derivation step, respectively. Either may be absent on
    # legacy blocks; in that case the model falls back to archetype +
    # evidence guidance only.
    section.extend(_story_role_guidance(block.get("story_role"), league_code))
    section.extend(_format_featured_players_section(block.get("featured_players")))

    section.extend(_format_evidence_block(evidence, league_code, home_team, away_team))

    contributors_line = _format_contributors_line(block.get("mini_box"), league_code)
    if contributors_line:
        section.append(contributors_line)

    if role == "RESOLUTION":
        section.extend(
            _format_resolution_extras(
                block, score_after, pbp_events, home_team, away_team, league_code,
                archetype,
            )
        )

    return section


def _format_resolution_extras(
    block: dict[str, Any],
    score_after: list[int],
    pbp_events: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    league_code: str,
    archetype: str | None,
) -> list[str]:
    final_margin = abs(score_after[0] - score_after[1])
    extras: list[str] = []

    if archetype in {"blowout", "early_avalanche_blowout"} or final_margin >= 15:
        extras.append(
            "(Outcome decided — state the final margin plainly; do not narrate garbage time.)"
        )
        return extras

    gw_hint = detect_game_winning_play(
        block, pbp_events, home_team, away_team, league_code,
    )
    if gw_hint:
        extras.append(f"*** {gw_hint} ***")
        extras.append(
            "- This play decided the game. Name the player, the action, and "
            "the moment — no generic 'held on' framing."
        )
    return extras


# ---------------------------------------------------------------------------
# Game-level flow pass prompt
# ---------------------------------------------------------------------------


GAME_FLOW_PASS_PROMPT = (
    "You are given the full Game Flow as a sequence of blocks. Each block is "
    "already correct in structure, scoring, and chronology. Rewrite for "
    "narrative coherence so the blocks flow as a single recap, while keeping "
    "each block as its own paragraph.\n\n"
    "Rules:\n"
    "- Preserve block order, boundaries, scores, periods, and player facts.\n"
    "- Preserve word-count discipline: each block stays 25-55 words.\n"
    "- Improve flow, reduce repetition, acknowledge time progression.\n"
    "- No hype, no speculation, no raw play-by-play.\n"
    "- SETUP blocks must NOT foreshadow the outcome.\n"
    "- RESPONSE blocks must reflect actual scoring movement.\n"
    "- Use full player/team name only on first mention across the whole flow; "
    "last name / short name thereafter.\n"
    "- If the game was already decided, say so plainly. If a segment was low "
    "leverage, compress it.\n"
    "- If the game went to overtime/OT/shootout/extra innings, the narrative "
    "MUST mention the transition.\n\n"
    'Return JSON: {"blocks": [{"i": block_index, "n": "revised narrative"}]}'
)


def build_game_flow_pass_prompt(
    blocks: list[dict[str, Any]],
    game_context: dict[str, str],
    *,
    archetype: str | None = None,
    regen_context: RegenFailureContext | None = None,
) -> str:
    """Build the prompt for the game-level flow pass (second OpenAI call).

    Receives all blocks at once and smooths transitions while preserving facts.
    Same archetype + banned-phrase constraints as the per-block prompt.
    """
    home_team = _sanitize_prompt_string(
        game_context.get("home_team_name"), default="Home"
    )
    away_team = _sanitize_prompt_string(
        game_context.get("away_team_name"), default="Away"
    )
    league_code = game_context.get("sport", "NBA")

    parts: list[str] = [
        GAME_FLOW_PASS_PROMPT,
        "",
        f"Game: {away_team} (away) at {home_team} (home)",
    ]
    parts.extend(_archetype_guidance(archetype))

    if league_code == "MLB":
        parts.append(
            f"\nREMINDER: {away_team} bats first (top of each inning), "
            f"{home_team} bats second (bottom). Do not say the home team "
            f"'struck first' if the away team scored in the top of the inning."
        )

    parts.extend([
        "",
        "BANNED PHRASES (do not use any of these, in any tense or variation):",
        _format_banned_phrases(),
    ])

    if regen_context is not None and regen_context.has_failures():
        parts.extend(["", regen_context.render_for_prompt()])

    parts.extend(["", "BLOCKS:"])

    for block in blocks:
        block_idx = block["block_index"]
        role = block.get("role", "")
        period_start = block.get("period_start", 1)
        period_end = block.get("period_end", period_start)
        score_before = block.get("score_before", [0, 0])
        score_after = block.get("score_after", [0, 0])
        narrative = block.get("narrative", "")

        ot_info = detect_overtime_info(block, league_code)
        period_label = _build_period_label(league_code, period_start, period_end)

        parts.append(f"\nBlock {block_idx} ({role}, {period_label}):")
        parts.append(
            f"Score: {away_team} {score_before[1]}-{score_before[0]} {home_team} "
            f"-> {away_team} {score_after[1]}-{score_after[0]} {home_team}"
        )

        if ot_info["enters_overtime"]:
            parts.append(f"*** MUST MENTION: Game goes to {ot_info['ot_label']} ***")

        parts.append(f"Current narrative: {narrative}")

    return "\n".join(parts)
