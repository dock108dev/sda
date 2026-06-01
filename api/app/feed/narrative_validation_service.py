"""Feed-level application of narrative validation outcomes."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.db.sports import SportsGame, SportsGamePlay

from .narrative_validation import (
    NarrativeFinding,
    NarrativeValidationContext,
    validate_card_text,
    validate_public_card_dto,
)
from .prompt_context import PromptContextWindow, build_prompt_window
from .schemas import NarrativeCard, SpoilerPolicy

_TEXT_FIELDS = (
    "lead_in",
    "stage_setting",
    "headline",
    "description",
    "setup_line",
    "play_line",
    "update_line",
    "impact",
)
_GENERIC_IMPORTANT_COPY_RE = re.compile(
    r"\b(?:scoring chance|key spot|important play|no-out spot)\b",
    re.IGNORECASE,
)
_DESCRIPTION_FUTURE_HINTS = (
    "would go on",
    "eventually",
    "later",
    "by the end",
    "in the end",
    "final score",
    "final result",
    "eventual outcome",
    "sealed the win",
    "seal the win",
    "for good",
)


@dataclass(frozen=True)
class CardValidationOutcome:
    """Validated card plus any findings that drove warnings or fallback text."""

    card: NarrativeCard | None
    findings: tuple[NarrativeFinding, ...]
    play_id: str
    play_index: int


def validate_feed_cards(
    *,
    game: SportsGame,
    sorted_plays: list[SportsGamePlay],
    cards: Iterable[NarrativeCard],
    spoiler_policy: SpoilerPolicy,
) -> list[CardValidationOutcome]:
    """Validate cards and substitute safe deterministic text when needed."""
    ordered_plays = sorted(sorted_plays, key=lambda play: play.play_index)
    final_score = _final_score(game, ordered_plays)
    player_ledger = _player_ledger(ordered_plays)
    game_context = _game_context(game)
    ordered_cards = sorted(cards, key=lambda card: card.play_index)
    outcomes: list[CardValidationOutcome] = []

    for card in ordered_cards:
        window = build_prompt_window(
            game=game_context,
            cards=ordered_cards,
            current_play_index=card.play_index,
        )
        context = _context_for_card(
            game=game,
            window=window,
            final_score=final_score,
            player_ledger=player_ledger,
            spoiler_policy=spoiler_policy,
        )
        findings: list[NarrativeFinding] = []
        replacement: dict[str, Any] = {}
        findings.extend(_validate_render_contract(card))
        for field in _TEXT_FIELDS:
            value = getattr(card, field)
            if not isinstance(value, str) or not value:
                continue
            field_findings = validate_card_text(text=value, field=field, context=context)
            findings.extend(field_findings)
            if any(f.action == "fallback_text" for f in field_findings):
                replacement[field] = _fallback_text(field, card)

        situation_summary = card.situation.summary
        if situation_summary:
            field_findings = validate_card_text(
                text=situation_summary,
                field="situation.summary",
                context=context,
            )
            findings.extend(field_findings)
            if any(f.action == "fallback_text" for f in field_findings):
                replacement["situation"] = card.situation.model_copy(
                    update={"summary": "Verified game context"}
                )

        checked_card = card.model_copy(update=replacement) if replacement else card
        dto = checked_card.model_dump(by_alias=True, mode="json", exclude_none=True)
        findings.extend(validate_public_card_dto(payload=dto, spoiler_policy=spoiler_policy))

        blocked = any(f.action == "block_card" for f in findings)
        outcomes.append(
            CardValidationOutcome(
                card=None if blocked else checked_card,
                findings=tuple(findings),
                play_id=card.source_play_id,
                play_index=card.play_index,
            )
        )
    return outcomes


def _validate_render_contract(card: NarrativeCard) -> list[NarrativeFinding]:
    findings: list[NarrativeFinding] = []
    if card.render_type == "important_narrative":
        for field in ("setup_line", "play_line", "update_line"):
            value = getattr(card, field)
            if not isinstance(value, str) or not value.strip():
                findings.append(
                    NarrativeFinding(
                        code="important_narrative_field_missing",
                        severity="error",
                        action="block_card",
                        message="Important narrative cards must include setup, play, and update lines.",
                        field=field,
                    )
                )
        for field in ("headline", "setup_line", "play_line", "update_line"):
            value = getattr(card, field)
            if isinstance(value, str) and _GENERIC_IMPORTANT_COPY_RE.search(value):
                findings.append(
                    NarrativeFinding(
                        code="important_narrative_generic_copy",
                        severity="error",
                        action="fallback_text",
                        message="Important narrative cards must not use generic setup titles.",
                        field=field,
                    )
                )
    elif any(getattr(card, field) for field in ("setup_line", "play_line", "update_line")):
        findings.append(
            NarrativeFinding(
                code="pbp_card_has_important_narrative_fields",
                severity="error",
                action="block_card",
                message="Standard and full PBP cards must not carry important narrative fields.",
                field="render_type",
            )
        )
    return findings


def _context_for_card(
    *,
    game: SportsGame,
    window: PromptContextWindow,
    final_score: tuple[int, int] | None,
    player_ledger: dict[str, int],
    spoiler_policy: SpoilerPolicy,
) -> NarrativeValidationContext:
    card = window.current_card
    current_play_index = int(card["playIndex"])
    allowed_cards = [*window.prior_cards, window.current_card]
    allowed_scores = {
        score
        for allowed_card in allowed_cards
        for score in _card_scores(allowed_card)
    }
    score_before = _score_from_mapping(card.get("scoreBefore"))
    score_after = _score_after_from_context(card)
    score_change = _score_change_from_mapping(card.get("scoreChange"))

    current_context_names = _extract_names_from_mapping(card)
    allowed_context_names = {
        name
        for allowed_card in allowed_cards
        for name in _extract_names_from_mapping(allowed_card)
    }
    allowed_names = {
        name for name, first_seen in player_ledger.items() if first_seen <= current_play_index
    } | current_context_names | allowed_context_names
    future_names = {
        name
        for name, first_seen in player_ledger.items()
        if first_seen > current_play_index and name not in allowed_names
    }
    home_abbr = game.home_team.abbreviation if game.home_team else None
    away_abbr = game.away_team.abbreviation if game.away_team else None
    return NarrativeValidationContext(
        home_team=game.home_team.name if game.home_team else None,
        away_team=game.away_team.name if game.away_team else None,
        home_abbrev=home_abbr,
        away_abbrev=away_abbr,
        home_aliases=_team_aliases(game.home_team.name if game.home_team else None, home_abbr),
        away_aliases=_team_aliases(game.away_team.name if game.away_team else None, away_abbr),
        current_play_index=current_play_index,
        allow_final_score=spoiler_policy is SpoilerPolicy.revealed,
        score_before=score_before,
        score_after=score_after,
        score_change=score_change,
        final_score=final_score,
        allowed_scores=frozenset(allowed_scores),
        allowed_player_names=frozenset(allowed_names),
        future_player_names=frozenset(future_names),
        scoring_side=_scoring_side(score_change),
    )


def _game_context(game: SportsGame) -> dict[str, Any]:
    return {
        "gameId": game.id,
        "homeTeam": game.home_team.name if game.home_team else None,
        "awayTeam": game.away_team.name if game.away_team else None,
        "homeTeamAbbr": game.home_team.abbreviation if game.home_team else None,
        "awayTeamAbbr": game.away_team.abbreviation if game.away_team else None,
    }


def _card_scores(card: dict[str, Any]) -> set[tuple[int, int]]:
    scores = set()
    before = _score_from_mapping(card.get("scoreBefore"))
    after = _score_after_from_context(card)
    if before:
        scores.add(before)
    if after:
        scores.add(after)
    return scores


def _score_from_mapping(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    return int(value["home"]), int(value["away"])


def _score_after_from_context(card: dict[str, Any]) -> tuple[int, int] | None:
    before = _score_from_mapping(card.get("scoreBefore"))
    if before is None:
        return None
    home_change, away_change = _score_change_from_mapping(card.get("scoreChange"))
    return before[0] + home_change, before[1] + away_change


def _score_change_from_mapping(value: Any) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        return (0, 0)
    return int(value.get("home") or 0), int(value.get("away") or 0)


def _final_score(game: SportsGame, ordered_plays: list[SportsGamePlay]) -> tuple[int, int] | None:
    home = getattr(game, "home_score", None)
    away = getattr(game, "away_score", None)
    if isinstance(home, int) and isinstance(away, int):
        return home, away
    for play in reversed(ordered_plays):
        if play.home_score is not None or play.away_score is not None:
            return play.home_score or 0, play.away_score or 0
    return None


def _player_ledger(ordered_plays: list[SportsGamePlay]) -> dict[str, int]:
    ledger: dict[str, int] = {}
    known_names: set[str] = set()
    for play in ordered_plays:
        known_names.update(_names_from_play(play))

    for play in ordered_plays:
        play_names = _names_from_play(play)
        description = play.description or ""
        if description and not _description_has_future_hint(description):
            play_names.update(name for name in known_names if _mentions_name(description, name))
        for normalized in play_names:
            if normalized:
                ledger[normalized] = min(play.play_index, ledger.get(normalized, play.play_index))
    return ledger


def _description_has_future_hint(value: str) -> bool:
    return any(_contains_phrase(value, hint) for hint in _DESCRIPTION_FUTURE_HINTS)


def _mentions_name(text: str, name: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, flags=re.IGNORECASE))


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"\s+".join(re.escape(part) for part in phrase.split())
    return bool(re.search(rf"(?<!\w){pattern}(?!\w)", text, flags=re.IGNORECASE))


def _names_from_play(play: SportsGamePlay) -> set[str]:
    raw_data = play.raw_data if isinstance(play.raw_data, dict) else {}
    names: set[str] = set()
    for name in {play.player_name or "", *_extract_names_from_mapping(raw_data)}:
        normalized = _clean_name(name)
        if normalized:
            names.add(normalized)
    return names


def _extract_names_from_mapping(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_name_key(str(key)) and isinstance(item, str):
                cleaned = _clean_name(item)
                if cleaned:
                    names.add(cleaned)
            else:
                names.update(_extract_names_from_mapping(item))
    elif isinstance(value, list | tuple):
        for item in value:
            names.update(_extract_names_from_mapping(item))
    return names


def _is_name_key(key: str) -> bool:
    return key.lower() in {
        "name",
        "fullname",
        "full_name",
        "playername",
        "player_name",
        "battername",
        "pitchername",
        "runnername",
    }


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned or len(cleaned.split()) < 2:
        return None
    return cleaned


def _team_aliases(name: str | None, abbreviation: str | None) -> frozenset[str]:
    aliases = {value.strip() for value in (name, abbreviation) if value and value.strip()}
    if name:
        parts = name.split()
        if len(parts) > 1:
            aliases.add(parts[-1])
    return frozenset(aliases)


def _scoring_side(value: tuple[int, int]) -> Literal["home", "away", "unknown"]:
    if value[0] and not value[1]:
        return "home"
    if value[1] and not value[0]:
        return "away"
    return "unknown"


def _fallback_text(field: str, card: NarrativeCard) -> str | None:
    if field in {"lead_in", "stage_setting"}:
        return card.display_time or card.period.label or "Game event"
    if field == "headline":
        return card.team.abbreviation or "Key play"
    if field == "description":
        return "Verified play detail is available after reveal."
    if field == "impact":
        return None
    if field == "setup_line":
        return card.stage_setting
    if field == "play_line":
        return card.description
    if field == "update_line":
        return card.impact or "Play complete."
    return "Verified game context"
