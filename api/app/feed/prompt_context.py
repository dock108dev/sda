"""Prompt context and templates for feed narrative-card text generation."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

from .schemas import CardFeedResponse, NarrativeCard

AllowedNarrativeField = Literal[
    "lead_in",
    "headline",
    "impact",
    "chapter_label",
    "situation_summary",
]

SYSTEM_PROMPT = (
    "You write short, factual text for one earned sports narrative card. "
    "Use only the supplied context window. Return strict JSON only."
)

_ALLOWED_FIELDS: tuple[AllowedNarrativeField, ...] = (
    "lead_in",
    "headline",
    "impact",
    "chapter_label",
    "situation_summary",
)

_FORBIDDEN_WORK = (
    "Do not calculate score math, period ordering, play ordering, tier eligibility, "
    "base/out calculation, drive state calculation, or final result calculation. "
    "Those are deterministic backend responsibilities. Do not mention final score, "
    "winner, eventual outcome, future plays, or players who are not present in this "
    "context window."
)


@dataclass(frozen=True)
class PromptContextWindow:
    """Spoiler-bounded card context used by sport prompt templates."""

    game: dict[str, Any]
    sport: str
    league: str
    current_play_index: int
    current_card: dict[str, Any]
    prior_cards: tuple[dict[str, Any], ...]
    prior_relevant_momentum: tuple[dict[str, Any], ...]
    ordering: dict[str, Any]
    regeneration: dict[str, Any]


@dataclass(frozen=True)
class CardPrompt:
    """Fully rendered prompt messages and deterministic input payload."""

    template_id: str
    system_prompt: str
    user_prompt: str
    model_input: dict[str, Any]


def build_prompt_windows(feed: CardFeedResponse) -> dict[int, PromptContextWindow]:
    """Build prompt windows for every card in a feed response."""
    cards = sorted(feed.cards, key=lambda card: card.play_index)
    return {
        card.play_index: build_prompt_window(
            game=feed.game.model_dump(mode="json", by_alias=True, exclude_none=True),
            cards=cards,
            current_play_index=card.play_index,
        )
        for card in cards
    }


def build_prompt_window(
    *,
    game: dict[str, Any],
    cards: Iterable[NarrativeCard],
    current_play_index: int,
) -> PromptContextWindow:
    """Build one deterministic context window containing no future cards."""
    ordered_cards = sorted(cards, key=lambda card: card.play_index)
    earned_cards = [card for card in ordered_cards if card.play_index <= current_play_index]
    if not earned_cards or earned_cards[-1].play_index != current_play_index:
        raise ValueError(f"No card exists at play index {current_play_index}")

    current = earned_cards[-1]
    sport = current.sport
    league = current.league
    game_context = _game_context(game, sport=sport, league=league)
    ordering = _ordering_context(earned_cards)
    prior = tuple(_card_context(card, ordering) for card in earned_cards[:-1])
    current_context = _card_context(current, ordering)
    momentum = _prior_relevant_momentum(prior)
    regeneration = _regeneration_context(
        game=game_context,
        current=current_context,
        prior=prior,
        ordering=ordering,
        momentum=momentum,
    )
    return PromptContextWindow(
        game=game_context,
        sport=sport,
        league=league,
        current_play_index=current_play_index,
        current_card=current_context,
        prior_cards=prior,
        prior_relevant_momentum=momentum,
        ordering=ordering,
        regeneration=regeneration,
    )


def build_card_prompt(window: PromptContextWindow) -> CardPrompt:
    """Render the sport-specific card prompt for one context window."""
    template = _template_for(window.sport)
    payload = {
        "game": window.game,
        "currentPlayIndex": window.current_play_index,
        "allowedOutputFields": list(_ALLOWED_FIELDS),
        "currentCard": window.current_card,
        "priorCards": list(window.prior_cards),
        "priorRelevantMomentum": list(window.prior_relevant_momentum),
        "ordering": window.ordering,
        "regeneration": window.regeneration,
    }
    prompt = "\n\n".join(
        [
            template["role"],
            template["focus"],
            _FORBIDDEN_WORK,
            (
                "Return JSON with exactly these string fields: "
                + ", ".join(_ALLOWED_FIELDS)
                + ". Keep each value under 18 words."
            ),
            "Context window JSON:\n" + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        ]
    )
    return CardPrompt(
        template_id=template["id"],
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        model_input=payload,
    )


def _game_context(game: dict[str, Any], *, sport: str, league: str) -> dict[str, Any]:
    return {
        "gameId": game.get("gameId"),
        "sport": sport,
        "league": league,
        "homeTeam": game.get("homeTeam"),
        "awayTeam": game.get("awayTeam"),
        "homeTeamAbbr": game.get("homeTeamAbbr"),
        "awayTeamAbbr": game.get("awayTeamAbbr"),
    }


def _card_context(card: NarrativeCard, ordering: dict[str, Any]) -> dict[str, Any]:
    raw = card.situation.raw or {}
    return _drop_none(
        {
            "cardId": card.id,
            "playIndex": card.play_index,
            "sourcePlayId": card.source_play_id,
            "stablePlayKey": ordering["playKeysByIndex"].get(str(card.play_index)),
            "period": card.period.model_dump(mode="json", exclude_none=True),
            "displayTime": card.display_time,
            "clock": card.clock,
            "team": card.team.model_dump(mode="json", exclude_none=True),
            "scoreBefore": _model_dump(card.score_before),
            "scoreChange": _model_dump(card.score_change),
            "situationSummary": card.situation.summary,
            "sportContext": _sport_context(card.sport, raw),
            "deterministicText": {
                "leadIn": card.lead_in,
                "headline": card.headline,
                "impact": card.impact,
                "description": card.description,
            },
        }
    )


def _sport_context(sport: str, raw: dict[str, Any]) -> dict[str, Any]:
    if sport == "baseball":
        return _drop_none(
            {
                "baseOut": raw.get("baseOut"),
                "matchup": raw.get("matchup"),
                "result": raw.get("result"),
                "flags": raw.get("flags"),
            }
        )
    if sport == "hockey":
        return _drop_none(
            {
                "clock": raw.get("clock"),
                "score": _score_pressure(raw),
                "strength": raw.get("strength"),
                "event": raw.get("event"),
                "flags": raw.get("flags"),
            }
        )
    if sport == "basketball":
        return _drop_none(
            {
                "clock": raw.get("clock"),
                "lead": raw.get("lead"),
                "run": raw.get("run"),
                "clutch": raw.get("clutch"),
                "result": raw.get("result"),
                "flags": raw.get("flags"),
            }
        )
    if sport == "football":
        return _drop_none(
            {
                "clock": raw.get("clock"),
                "drive": raw.get("drive"),
                "result": raw.get("result"),
                "flags": raw.get("flags"),
            }
        )
    return {}


def _ordering_context(cards: list[NarrativeCard]) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    for card in cards:
        source_id = _normalized_source_id(card.source_play_id)
        if source_id is not None:
            source_counts[source_id] = source_counts.get(source_id, 0) + 1

    duplicate_source_ids = tuple(
        sorted(source_id for source_id, count in source_counts.items() if count > 1)
    )
    duplicate_set = set(duplicate_source_ids)
    play_keys_by_index = {
        str(card.play_index): _stable_play_key(card, duplicate_set)
        for card in cards
    }
    return {
        "strategy": "source_id_else_sequence",
        "orderedPlayKeys": [play_keys_by_index[str(card.play_index)] for card in cards],
        "playKeysByIndex": play_keys_by_index,
        "duplicateSourcePlayIds": list(duplicate_source_ids),
        "missingSourcePlayIndices": [
            card.play_index for card in cards if _normalized_source_id(card.source_play_id) is None
        ],
        "skippedPlayIndices": _skipped_play_indices(cards),
        "scoreCorrectionPlayIndices": _score_correction_indices(cards),
    }


def _stable_play_key(card: NarrativeCard, duplicate_source_ids: set[str]) -> str:
    source_id = _normalized_source_id(card.source_play_id)
    if source_id is None or source_id in duplicate_source_ids:
        return f"sequence:{card.play_index}"
    return f"source:{source_id}"


def _normalized_source_id(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() in {"none", "null"}:
        return None
    return stripped


def _skipped_play_indices(cards: list[NarrativeCard]) -> list[int]:
    if len(cards) < 2:
        return []
    observed = {card.play_index for card in cards}
    start = min(observed)
    end = max(observed)
    return [index for index in range(start, end + 1) if index not in observed]


def _score_correction_indices(cards: list[NarrativeCard]) -> list[int]:
    corrections: list[int] = []
    expected_score: tuple[int, int] | None = None
    for card in cards:
        before = _score_tuple(card.score_before)
        if expected_score is not None and before is not None and before != expected_score:
            corrections.append(card.play_index)
        expected_score = _score_after_tuple(card)
    return corrections


def _score_after_tuple(card: NarrativeCard) -> tuple[int, int] | None:
    before = _score_tuple(card.score_before)
    if before is None:
        return None
    change = card.score_change
    if change is None:
        return before
    return before[0] + change.home, before[1] + change.away


def _score_tuple(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    return int(value.home), int(value.away)


def _prior_relevant_momentum(prior_cards: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    relevant: list[dict[str, Any]] = []
    for card in prior_cards:
        score_change = card.get("scoreChange") or {}
        text = card.get("deterministicText") or {}
        impact = text.get("impact")
        if score_change.get("home") or score_change.get("away") or impact:
            relevant.append(
                _drop_none(
                    {
                        "playIndex": card.get("playIndex"),
                        "stablePlayKey": card.get("stablePlayKey"),
                        "displayTime": card.get("displayTime"),
                        "team": card.get("team"),
                        "scoreChange": card.get("scoreChange"),
                        "impact": impact,
                        "headline": text.get("headline"),
                    }
                )
            )
    return tuple(relevant[-5:])


def _regeneration_context(
    *,
    game: dict[str, Any],
    current: dict[str, Any],
    prior: tuple[dict[str, Any], ...],
    ordering: dict[str, Any],
    momentum: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    payload = {
        "game": game,
        "currentCard": current,
        "priorCards": list(prior),
        "priorRelevantMomentum": list(momentum),
        "ordering": ordering,
    }
    reason_codes = ["window_hash_changed"] + [
        code
        for key, code in (
            ("duplicateSourcePlayIds", "duplicate_source_ids_fallback_to_sequence"),
            ("missingSourcePlayIndices", "missing_source_ids_fallback_to_sequence"),
            ("skippedPlayIndices", "skipped_play_indices_present"),
            ("scoreCorrectionPlayIndices", "score_corrections_present"),
        )
        if ordering.get(key)
    ]
    return {
        "contextHash": sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "currentCardId": current.get("cardId"),
        "currentPlayKey": current.get("stablePlayKey"),
        "changePolicy": "regenerate_when_context_hash_changes",
        "reasonCodes": reason_codes,
    }


def _score_pressure(raw: dict[str, Any]) -> dict[str, Any] | None:
    score = raw.get("score")
    if not isinstance(score, dict):
        return None
    return _drop_none(
        {
            "impact": score.get("impact"),
            "marginBefore": score.get("marginBefore"),
            "marginAfter": score.get("marginAfter"),
            "change": score.get("change"),
        }
    )


def _template_for(sport: str) -> dict[str, str]:
    templates = {
        "baseball": {
            "id": "feed-card-mlb-v1",
            "role": "Template: MLB earned-card prose.",
            "focus": (
                "Prioritize inning half, outs, base state, runners, batter, pitcher, "
                "count, and the current play result."
            ),
        },
        "hockey": {
            "id": "feed-card-nhl-v1",
            "role": "Template: NHL earned-card prose.",
            "focus": (
                "Prioritize clock, score pressure, special teams, goalie-pulled state, "
                "shot/penalty context, and the current event."
            ),
        },
        "basketball": {
            "id": "feed-card-basketball-v1",
            "role": "Template: basketball earned-card prose.",
            "focus": (
                "Prioritize runs, lead context, clutch window, shot or possession result, "
                "and whether the current card changes pressure."
            ),
        },
        "football": {
            "id": "feed-card-football-v1",
            "role": "Template: football earned-card prose.",
            "focus": (
                "Prioritize drive context, down, distance, field position, yardage, "
                "turnovers, fourth-down stakes, red-zone stakes, and clock pressure."
            ),
        },
    }
    try:
        return templates[sport]
    except KeyError as exc:
        raise ValueError(f"Unsupported prompt sport: {sport}") from exc


def _model_dump(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.model_dump(mode="json", exclude_none=True)


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
