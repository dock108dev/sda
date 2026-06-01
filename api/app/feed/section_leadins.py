"""Build deterministic period lead-ins for normalized card feeds."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .schemas import CardPeriod, CardSectionLeadIn, NarrativeCard

_SCORE_PAIR_RE = re.compile(r"\b\d{1,3}\s*(?:-|–|—|to)\s*\d{1,3}\b", re.IGNORECASE)
_UNSAFE_GENERATED_PHRASES = (
    "eventually",
    "later",
    "by the end",
    "in the end",
    "final score",
    "winner",
    "wins",
    "won",
    "victory",
    "defeated",
    "sealed",
    "clinched",
    "for good",
)


def build_section_lead_ins(cards: list[NarrativeCard]) -> list[CardSectionLeadIn]:
    """Return one stable lead-in for each deterministic period group."""
    sections: list[CardSectionLeadIn] = []
    prior_count = 0
    for ordinal, section_cards in enumerate(_period_groups(cards), start=1):
        first = section_cards[0]
        last = section_cards[-1]
        title = _period_title(first.league, first.period)
        generated = _generated_lead_in(first)
        fallback = _neutral_lead_in(title, prior_count)
        source = "deterministic"
        lead_in = fallback
        if generated:
            if _generated_text_is_safe(generated):
                lead_in = generated
                source = "generated"
            else:
                source = "fallback"
        sections.append(
            CardSectionLeadIn(
                id=_section_id(first),
                ordinal=ordinal,
                period=first.period,
                label=first.period.label or title,
                title=title,
                leadIn=lead_in,
                startPlayIndex=first.play_index,
                endPlayIndex=last.play_index,
                source=source,
            )
        )
        prior_count += len(section_cards)
    return sections


def _period_groups(cards: list[NarrativeCard]) -> list[list[NarrativeCard]]:
    ordered = sorted(cards, key=lambda card: card.play_index)
    groups: list[list[NarrativeCard]] = []
    for card in ordered:
        if groups and _period_key(groups[-1][0]) == _period_key(card):
            groups[-1].append(card)
        else:
            groups.append([card])
    return groups


def _period_key(card: NarrativeCard) -> tuple[int | None, str | None, str | None]:
    return card.period.ordinal, card.period.label, card.period.type


def _section_id(card: NarrativeCard) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (card.period.label or "unknown").lower()).strip("-")
    return f"{card.game_id}:period:{card.period.ordinal or 'unknown'}:{slug or 'section'}"


def _period_title(league: str, period: CardPeriod) -> str:
    label = (period.label or "").strip()
    ordinal = period.ordinal
    if league == "MLB":
        return _baseball_period_title(label, ordinal)
    if league == "NHL":
        if period.type == "OT" or label.upper().startswith("OT"):
            return "Overtime"
        if period.type == "SO" or "shootout" in label.lower():
            return "Shootout"
        return f"{_ordinal_word(ordinal)} period" if ordinal else label or "Period"
    if league == "NCAAB":
        if ordinal and ordinal > 2:
            return "Overtime" if ordinal == 3 else f"{_ordinal_word(ordinal - 2)} overtime"
        return f"{_ordinal_word(ordinal)} half" if ordinal else label or "Half"
    if league in {"NBA", "NFL", "NCAAF"}:
        if ordinal and ordinal > 4:
            return "Overtime" if ordinal == 5 else f"{_ordinal_word(ordinal - 4)} overtime"
        noun = "quarter"
        return f"{_ordinal_word(ordinal)} {noun}" if ordinal else label or "Period"
    return label or (f"Period {ordinal}" if ordinal else "Period")


def _baseball_period_title(label: str, ordinal: int | None) -> str:
    normalized = label.upper().replace(" ", "")
    inning = ordinal
    if len(normalized) >= 2 and normalized[1:].isdigit():
        inning = int(normalized[1:])
        if normalized.startswith("T"):
            return f"Top {_ordinal_number(inning)}"
        if normalized.startswith("B"):
            return f"Bottom {_ordinal_number(inning)}"
    if "top" in label.lower() or "bottom" in label.lower():
        return label
    return f"{_ordinal_number(inning)} inning" if inning else label or "Inning"


def _neutral_lead_in(title: str, prior_count: int) -> str:
    if prior_count <= 0:
        return f"{title} opens the feed."
    play_word = "play" if prior_count == 1 else "plays"
    return f"{title} begins after {prior_count} earlier {play_word}."


def _generated_lead_in(card: NarrativeCard) -> str | None:
    raw = card.situation.raw
    if not isinstance(raw, Mapping):
        return None
    candidates: list[Any] = [
        raw.get("sectionLeadIn"),
        raw.get("chapterLeadIn"),
        raw.get("periodLeadIn"),
    ]
    narrative = raw.get("narrative")
    if isinstance(narrative, Mapping):
        candidates.extend(
            [
                narrative.get("sectionLeadIn"),
                narrative.get("chapterLeadIn"),
                narrative.get("periodLeadIn"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, str):
            cleaned = _clean(candidate)
            if cleaned:
                return cleaned
    return None


def _generated_text_is_safe(value: str) -> bool:
    lowered = value.lower()
    return not (
        _SCORE_PAIR_RE.search(value)
        or any(phrase in lowered for phrase in _UNSAFE_GENERATED_PHRASES)
    )


def _ordinal_word(value: int | None) -> str:
    words = {
        1: "First",
        2: "Second",
        3: "Third",
        4: "Fourth",
        5: "Fifth",
        6: "Sixth",
    }
    if value is None:
        return "Next"
    return words.get(value, _ordinal_number(value))


def _ordinal_number(value: int | None) -> str:
    if value is None:
        return "next"
    suffix = "th"
    if value % 100 not in {11, 12, 13}:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
