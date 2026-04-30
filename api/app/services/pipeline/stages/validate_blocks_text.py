"""Text normalization, sentence counting, and coverage string checks for validate_blocks."""

from __future__ import annotations

import re
from typing import Any

from .validate_blocks_constants import COMMON_ABBREVIATIONS, OT_TERMS


def normalize_text(text: str) -> str:
    """Lowercase and collapse whitespace for coverage matching."""
    return re.sub(r"\s+", " ", text.lower().strip())


def check_score_present(text: str, home: int, away: int) -> bool:
    """Return True if the score (either order) appears in text.

    Handles hyphens, en/em dashes, and written-out 'X to Y' forms.
    """
    norm = normalize_text(text)
    sep = r"\s*[-\u2013\u2014]\s*|\s+to\s+"
    patterns = [
        rf"\b{home}(?:{sep}){away}\b",
        rf"\b{away}(?:{sep}){home}\b",
    ]
    return any(re.search(p, norm) for p in patterns)


def check_team_present(text: str, team: str) -> bool:
    """Return True if the team name (or its nickname) appears in text."""
    norm = normalize_text(text)
    parts = team.split()
    variants = [normalize_text(team)]
    if len(parts) > 1:
        variants.append(parts[-1].lower())
    return any(v in norm for v in variants)


def check_ot_present(text: str) -> bool:
    """Return True if any overtime indicator appears in text."""
    norm = normalize_text(text)
    padded = f" {norm} "
    return any(term in padded for term in OT_TERMS)


def count_sentences(text: str) -> int:
    """Count sentences using . ! ? with abbreviation guards.

    Used for soft validation warnings (not hard failures).
    """
    if not text:
        return 0

    protected = text
    for abbrev in COMMON_ABBREVIATIONS:
        pattern = re.escape(abbrev)
        protected = re.sub(pattern, abbrev.replace(".", "\x00"), protected, flags=re.IGNORECASE)

    protected = re.sub(r"\.{2,}", "\x00", protected)
    sentences = re.split(r"[.!?]+", protected)
    return len([s for s in sentences if s.strip()])


def validate_narrative_coverage(
    blocks: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    has_overtime: bool,
) -> tuple[list[str], list[str]]:
    """Validate narrative coverage: final score, winning team, OT if applicable."""
    errors: list[str] = []
    warnings: list[str] = []

    full_text = " ".join(b.get("narrative", "") for b in blocks if b.get("narrative")).strip()

    if not full_text:
        errors.append("Coverage: No narrative text to validate")
        return errors, warnings

    if home_score == 0 and away_score == 0:
        warnings.append("Coverage: Score data unavailable, skipping score/winner checks")
    else:
        if not check_score_present(full_text, home_score, away_score):
            errors.append(
                f"Coverage: Final score {home_score}-{away_score} not mentioned in narrative"
            )

        if home_score != away_score:
            winning_team = home_team if home_score > away_score else away_team
            if winning_team and not check_team_present(full_text, winning_team):
                errors.append(f"Coverage: Winning team '{winning_team}' not mentioned in narrative")

    if has_overtime and not check_ot_present(full_text):
        errors.append("Coverage: Game went to overtime but no OT mention found in narrative")

    return errors, warnings
