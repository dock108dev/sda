"""Consolidated prompt builder for the catch-up game summary.

Single LLM call per game. The prompt produces a 3-5 paragraph narrative
summary plus the list of play_ids the summary actually references, used
downstream so catch-up cards can link back to the same plays.

Sport-specific vocabulary (period_noun, score_noun, extra_period_label) is
injected from league_config rather than branched in prose. Archetype is
passed through as a one-line tone hint, not as separate prompt variants.
"""

from __future__ import annotations

import json
from typing import Any

from .league_config import _NBA_DEFAULTS, LEAGUE_CONFIG

SYSTEM_PROMPT = (
    "You are a sports columnist writing a short, narrative recap of a "
    "completed game. Use only the facts given to you. Do not invent "
    "players, plays, scores, or motivations. Write in active voice. "
    "Name standout players naturally as the events warrant. Do not lead "
    "with the final score. Do not use empty cliches "
    "('left it all on the field', 'gave 110%', 'set the tone'). The final "
    "score should appear in context within the recap, not as a header. "
    "Return strict JSON only — no prose outside the JSON object."
)

# Archetype -> one-line tone hint. Kept short on purpose; longer guidance
# pushes the model toward formulaic output.
_ARCHETYPE_HINTS: dict[str, str] = {
    "blowout": (
        "This was a blowout. Lead with the stretch that broke it open. "
        "Don't manufacture drama that wasn't there."
    ),
    "early_avalanche_blowout": (
        "Early innings put this away. Frame the avalanche, then describe "
        "how the rest of the game played out under that weight."
    ),
    "comeback": (
        "The eventual winner trailed by a real margin. Frame the deficit "
        "and the moment things turned. Name who drove the comeback."
    ),
    "back_and_forth": (
        "Multiple lead changes. Lean on the swings and on whichever play "
        "finally tipped it for good."
    ),
    "low_event": (
        "Scoring was scarce — that scarcity is the story. Lead with "
        "pitching/defense before offense; small events carry weight."
    ),
    "fake_close": (
        "The final margin is misleading. The winner controlled most of "
        "the game and let it tighten late. Say so plainly."
    ),
    "late_separation": (
        "It was close until the final period, when one stretch decided it. "
        "Build to that stretch; don't bury it."
    ),
    "wire_to_wire": (
        "The winner led throughout. Describe how they kept the gap rather "
        "than fabricating turning points."
    ),
}

# One paragraph-form few-shot, kept generic so the model doesn't ape sport-
# specific vocabulary.
_FEW_SHOT_EXAMPLE = (
    "Example output (format only — do not copy content):\n"
    '{"summary": ['
    '"The visitors set the tempo early and never quite let it go, opening '
    "a nine-point cushion before the home side could find a rhythm. "
    "Mitchell carried the early scoring; the home defense had no answer "
    'for his pull-up.", '
    '"A third-quarter run from the home bench cut the lead to two with '
    "under five minutes left, and for a stretch the building thought "
    'this was going to be a different game.", '
    '"It wasn\'t. The visitors answered with a 9-0 run of their own — '
    "two threes from Edwards, a transition dunk — and the lead was back "
    'into double digits before the home side scored again.", '
    '"Edwards finished with 31 and seven assists; Mitchell added 24. The '
    'home side got 28 from Brown but shot 3-of-19 from deep as a team.", '
    '"Final: visitors 118, home 109."'
    '], "referenced_play_ids": [12, 47, 102, 138, 201]}'
)


def _league_vocab(league_code: str) -> dict[str, str]:
    """Pull period/score nouns from league_config, falling back to NBA."""
    cfg = LEAGUE_CONFIG.get((league_code or "").upper(), _NBA_DEFAULTS)
    return {
        "period_noun": cfg.get("period_noun", "quarter"),
        "score_noun": cfg.get("score_noun", "point"),
        "extra_period_label": cfg.get("extra_period_label", "overtime"),
    }


def _format_play(play: dict[str, Any], period_noun: str) -> str:
    """One-line description of a key play for the prompt body."""
    play_id = play.get("play_index", play.get("play_id", "?"))
    period = play.get("quarter") or play.get("period") or 1
    clock = play.get("game_clock") or play.get("clock")
    desc = play.get("description") or play.get("play_type") or "(no description)"
    home = play.get("home_score")
    away = play.get("away_score")
    pieces = [f"id={play_id}", f"{period_noun} {period}"]
    if clock:
        pieces.append(f"@{clock}")
    if home is not None and away is not None:
        pieces.append(f"score {home}-{away}")
    return f"- {' | '.join(pieces)}: {desc}"


def _format_period_breakdown(by_period: list[tuple[int, int]] | None, period_noun: str) -> str:
    """Render per-period scoring as a one-line table when available."""
    if not by_period:
        return ""
    parts = []
    for i, (h, a) in enumerate(by_period, start=1):
        parts.append(f"{period_noun} {i}: {h}-{a}")
    return "Score by " + period_noun + ": " + "; ".join(parts)


def build_summary_prompt(
    *,
    league_code: str,
    home_team: str,
    away_team: str,
    home_abbrev: str,
    away_abbrev: str,
    home_final: int,
    away_final: int,
    archetype: str | None,
    key_plays: list[dict[str, Any]],
    by_period: list[tuple[int, int]] | None = None,
    standout_players: list[dict[str, Any]] | None = None,
) -> str:
    """Build the user-message prompt for the single summary LLM call.

    Returns a string. The caller (generate_summary stage) is responsible for
    pairing it with SYSTEM_PROMPT and submitting to the OpenAI client in
    JSON mode.
    """
    vocab = _league_vocab(league_code)
    period_noun = vocab["period_noun"]
    score_noun = vocab["score_noun"]
    extra_label = vocab["extra_period_label"]

    archetype_hint = _ARCHETYPE_HINTS.get(
        archetype or "",
        "No specific archetype hint. Let the plays drive the framing.",
    )

    plays_block = "\n".join(_format_play(p, period_noun) for p in key_plays) or "(no key plays available)"
    period_breakdown = _format_period_breakdown(by_period, period_noun)

    standouts_block = ""
    if standout_players:
        rows = []
        for p in standout_players:
            name = p.get("name", "?")
            team = p.get("team", "?")
            stats = p.get("stat_summary") or p.get("statSummary") or ""
            rows.append(f"- {name} ({team}): {stats}".rstrip(": "))
        standouts_block = "Standout players:\n" + "\n".join(rows)

    sections = [
        f"League: {league_code}. Period unit: {period_noun}. Score unit: {score_noun}. "
        f"Extra periods (if any) called: {extra_label}.",
        f"Final score: {away_team} ({away_abbrev}) {away_final}, "
        f"{home_team} ({home_abbrev}) {home_final}.",
    ]
    if period_breakdown:
        sections.append(period_breakdown)
    sections.append(f"Game shape (deterministic classification): {archetype or 'unknown'}.")
    sections.append(f"Tone hint for this shape: {archetype_hint}")
    sections.append("Key plays (chronological order, only narrate plays from this list):")
    sections.append(plays_block)
    if standouts_block:
        sections.append(standouts_block)

    sections.append(
        "Write a 3-5 paragraph recap. Each paragraph 2-4 sentences. "
        "Plain text — no markdown, no bullet points, no headers. The final "
        "score should appear in the closing paragraph, naturally embedded "
        "in the prose. Reference plays by their content; do not cite "
        "play ids in the prose."
    )
    sections.append(
        "Return JSON: "
        '{"summary": [paragraph_1, paragraph_2, ...], '
        '"referenced_play_ids": [int, ...]}. '
        "The referenced_play_ids list contains the ids of the key plays "
        "the recap actually leans on (subset of the key plays list above). "
        "Do not include ids you did not narrate."
    )
    sections.append(_FEW_SHOT_EXAMPLE)

    return "\n\n".join(sections)


def parse_summary_response(content: str) -> dict[str, Any]:
    """Validate and normalize the model's JSON response.

    Returns ``{"summary": list[str], "referenced_play_ids": list[int]}``.
    Raises ``ValueError`` on malformed shape — the caller decides whether to
    retry or fall through.
    """
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Summary response is not a JSON object")

    summary = parsed.get("summary")
    if not isinstance(summary, list) or not summary:
        raise ValueError("Summary response missing 'summary' array")
    if not all(isinstance(p, str) and p.strip() for p in summary):
        raise ValueError("Summary paragraphs must be non-empty strings")
    if not (3 <= len(summary) <= 5):
        raise ValueError(
            f"Summary must have 3-5 paragraphs, got {len(summary)}"
        )

    raw_ids = parsed.get("referenced_play_ids", [])
    if not isinstance(raw_ids, list):
        raise ValueError("referenced_play_ids must be a list")
    referenced: list[int] = []
    for pid in raw_ids:
        try:
            referenced.append(int(pid))
        except (TypeError, ValueError):
            continue

    return {"summary": summary, "referenced_play_ids": referenced}
