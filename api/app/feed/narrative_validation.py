"""Deterministic validation for feed card narrative text and public DTOs."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

FindingSeverity = Literal["warning", "error"]
FindingAction = Literal["serve", "fallback_text", "block_card"]


@dataclass(frozen=True)
class NarrativeFinding:
    """One deterministic narrative validation outcome."""

    code: str
    severity: FindingSeverity
    action: FindingAction
    message: str
    field: str | None = None


@dataclass(frozen=True)
class NarrativeValidationContext:
    """Spoiler-bounded facts used to validate one card's text."""

    home_team: str | None
    away_team: str | None
    home_abbrev: str | None
    away_abbrev: str | None
    home_aliases: frozenset[str]
    away_aliases: frozenset[str]
    current_play_index: int
    allow_final_score: bool
    score_before: tuple[int, int] | None
    score_after: tuple[int, int] | None
    score_change: tuple[int, int]
    final_score: tuple[int, int] | None
    allowed_scores: frozenset[tuple[int, int]]
    allowed_player_names: frozenset[str]
    future_player_names: frozenset[str]
    scoring_side: Literal["home", "away", "unknown"]


_SCORE_PAIR_RE = re.compile(r"\b(\d{1,3})\s*(?:-|–|—|to)\s*(\d{1,3})\b", re.IGNORECASE)
_MARGIN_RE = re.compile(
    r"\bby\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\b",
    re.IGNORECASE,
)
_FUTURE_PHRASES = (
    "would go on to",
    "eventually",
    "later",
    "by the end",
    "in the end",
    "final score",
    "final result",
    "eventual outcome",
    "walked it off",
    "sealed the win",
    "seal the win",
    "closed out the win",
    "clinched",
    "never trailed again",
    "for good",
    "put away",
    "put-away",
)
_WINNER_RE = re.compile(
    r"\b(?:won|wins|win|winner|victory|beat|beats|defeated|defeats|prevailed|"
    r"held on|closed out|sealed|seal|completed the comeback|game-winning)\b",
    re.IGNORECASE,
)
_HOME_ROLE_RE = re.compile(
    r"\b(?:home team|home side|home club|at home|home floor|home crowd|hosted|hosts)\b",
    re.IGNORECASE,
)
_AWAY_ROLE_RE = re.compile(
    r"\b(?:visitors?|away team|away side|away club|on the road|road win|road loss)\b",
    re.IGNORECASE,
)
_SCORING_RE = re.compile(
    r"\b(?:scores?|adds?|puts up|gets|cash(?:es)? in|cuts the gap|ties it|takes? the lead)\b",
    re.IGNORECASE,
)
_MESSAGES = {
    "narrative_future_outcome_phrase": "Narrative text uses future-outcome language before the current play.",
    "narrative_final_score_leak": "Narrative text contains the final score before the current play.",
    "narrative_winner_leak": "Narrative text names a winner before the current play.",
    "narrative_score_not_allowed": "Narrative text contains a score outside the allowed card state.",
    "narrative_score_team_order_mismatch": "Narrative text attributes score values to the wrong teams.",
    "narrative_margin_mismatch": "Narrative text describes a margin inconsistent with the card score.",
    "narrative_home_away_role_mismatch": "Narrative text assigns home or away role to the wrong team.",
    "narrative_winner_team_mismatch": "Narrative winner language conflicts with the game score.",
    "narrative_team_score_mismatch": "Narrative scoring language conflicts with the scoring team.",
    "narrative_future_player_mention": "Narrative text mentions a player outside the allowed play window.",
}


def validate_card_text(
    *,
    text: str,
    field: str,
    context: NarrativeValidationContext,
) -> list[NarrativeFinding]:
    """Validate one generated or candidate narrative field against allowed facts."""
    findings: list[NarrativeFinding] = []
    if not text.strip():
        return findings

    has_future_phrase = _has_future_phrase(text)
    if has_future_phrase:
        findings.append(_finding("narrative_future_outcome_phrase", "warning", "serve", field))

    findings.extend(_score_findings(text, field, context))
    findings.extend(_team_findings(text, field, context))
    findings.extend(_player_findings(text, field, context))

    if not context.allow_final_score and _WINNER_RE.search(text):
        has_team = _contains_any_alias(text, context.home_aliases | context.away_aliases)
        if has_team or has_future_phrase:
            findings.append(_finding("narrative_winner_leak", "error", "fallback_text", field))

    if has_future_phrase and any(f.severity == "error" for f in findings):
        findings = [
            _finding("narrative_future_outcome_phrase", "error", "fallback_text", field)
            if f.code == "narrative_future_outcome_phrase"
            else f
            for f in findings
        ]
    return findings


def issue_codes(findings: Iterable[NarrativeFinding]) -> list[str]:
    """Return stable issue codes suitable for generation metadata."""
    return list(dict.fromkeys(finding.code for finding in findings))


def _score_findings(
    text: str,
    field: str,
    context: NarrativeValidationContext,
) -> list[NarrativeFinding]:
    findings: list[NarrativeFinding] = []
    allowed_any_order = context.allowed_scores | {_reverse(pair) for pair in context.allowed_scores}
    final_any_order = _score_pair_options(context.final_score)

    for match in _SCORE_PAIR_RE.finditer(text):
        pair = (int(match.group(1)), int(match.group(2)))
        if (
            not context.allow_final_score
            and context.final_score is not None
            and pair in final_any_order
            and (pair not in allowed_any_order or _has_outcome_language(text))
        ):
            findings.append(_finding("narrative_final_score_leak", "error", "fallback_text", field))
            continue
        if allowed_any_order and pair not in allowed_any_order:
            findings.append(_finding("narrative_score_not_allowed", "error", "fallback_text", field))
            continue
        if _team_order_mismatch(text, pair, context):
            findings.append(
                _finding("narrative_score_team_order_mismatch", "error", "fallback_text", field)
            )

    allowed_margins = _allowed_margins(context)
    for match in _MARGIN_RE.finditer(text):
        margin = _margin_value(match.group(1))
        if margin is not None and allowed_margins and margin not in allowed_margins:
            findings.append(_finding("narrative_margin_mismatch", "error", "fallback_text", field))
    return findings


def _team_findings(
    text: str,
    field: str,
    context: NarrativeValidationContext,
) -> list[NarrativeFinding]:
    findings: list[NarrativeFinding] = []
    for sentence in _sentences(text):
        has_home = _contains_any_alias(sentence, context.home_aliases)
        has_away = _contains_any_alias(sentence, context.away_aliases)
        if has_away and _HOME_ROLE_RE.search(sentence):
            findings.append(_finding("narrative_home_away_role_mismatch", "error", "fallback_text", field))
        if has_home and _AWAY_ROLE_RE.search(sentence):
            findings.append(_finding("narrative_home_away_role_mismatch", "error", "fallback_text", field))
        if context.scoring_side == "home" and has_away and not has_home and _SCORING_RE.search(sentence):
            findings.append(_finding("narrative_team_score_mismatch", "error", "fallback_text", field))
        if context.scoring_side == "away" and has_home and not has_away and _SCORING_RE.search(sentence):
            findings.append(_finding("narrative_team_score_mismatch", "error", "fallback_text", field))

    if context.allow_final_score and context.final_score is not None:
        home, away = context.final_score
        loser_aliases = context.away_aliases if home > away else context.home_aliases if away > home else frozenset()
        if loser_aliases and _contains_any_alias(text, loser_aliases) and _WINNER_RE.search(text):
            findings.append(_finding("narrative_winner_team_mismatch", "error", "fallback_text", field))
    return findings


def _player_findings(
    text: str,
    field: str,
    context: NarrativeValidationContext,
) -> list[NarrativeFinding]:
    return [
        _finding("narrative_future_player_mention", "error", "fallback_text", field)
        for name in context.future_player_names
        if _contains_alias(text, name)
    ]


def _has_outcome_language(text: str) -> bool:
    return _WINNER_RE.search(text) is not None or _has_future_phrase(text)


def _has_future_phrase(text: str) -> bool:
    return any(_contains_phrase(text, phrase) for phrase in _FUTURE_PHRASES)


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"\s+".join(re.escape(part) for part in phrase.split())
    return bool(re.search(rf"(?<!\w){pattern}(?!\w)", text, flags=re.IGNORECASE))


def _team_order_mismatch(
    text: str,
    pair: tuple[int, int],
    context: NarrativeValidationContext,
) -> bool:
    if pair in context.allowed_scores:
        return False
    reverse = _reverse(pair)
    if reverse not in context.allowed_scores:
        return False
    home_pos = _first_alias_position(text, context.home_aliases)
    away_pos = _first_alias_position(text, context.away_aliases)
    if home_pos is None or away_pos is None:
        return False
    return home_pos < away_pos


def _allowed_margins(context: NarrativeValidationContext) -> set[int]:
    margins = {abs(home - away) for home, away in context.allowed_scores}
    if context.score_change != (0, 0):
        margins.add(sum(context.score_change))
    return margins


def _score_pair_options(score: tuple[int, int] | None) -> set[tuple[int, int]]:
    if score is None:
        return set()
    return {score, _reverse(score)}


def _reverse(pair: tuple[int, int]) -> tuple[int, int]:
    return pair[1], pair[0]


def _margin_value(value: str) -> int | None:
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    return words.get(value.lower(), int(value) if value.isdigit() else None)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _contains_any_alias(text: str, aliases: Iterable[str]) -> bool:
    return any(_contains_alias(text, alias) for alias in aliases)


def _contains_alias(text: str, alias: str) -> bool:
    if not alias:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, flags=re.IGNORECASE))


def _first_alias_position(text: str, aliases: Iterable[str]) -> int | None:
    positions = [
        match.start()
        for alias in aliases
        for match in [re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, flags=re.IGNORECASE)]
        if match
    ]
    return min(positions) if positions else None


def _finding(
    code: str,
    severity: FindingSeverity,
    action: FindingAction,
    field: str | None,
) -> NarrativeFinding:
    return NarrativeFinding(
        code=code,
        severity=severity,
        action=action,
        message=_MESSAGES[code],
        field=field,
    )
