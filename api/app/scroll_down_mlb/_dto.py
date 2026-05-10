"""Built-deck → spoiler-safe wire DTO conversion.

Strips post-play score (the spoiler-safety contract forbids it on /deck)
and rewrites internal `BuiltPlayCard` shapes into Pydantic models that
serialize as camelCase JSON. The final-score-leak scan also lives here
so its logic sits next to the DTO it scans.

Findings from `scan_response_for_final_score_leaks` are intentionally
returned to the caller (not appended to `response.validation_warnings`)
so the pipeline can re-run policy and decide blocking before persisting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .internal_types import BuiltPlayCard, RunnerAdvance
from .narrative import narrative_for_card
from .result_labels import result_chip_label
from .rhythm_planner import DeckItem
from .schemas import (
    BaseState,
    DeckCardType,
    PlannerNote,
    PlayPayload,
    RunnerMovement,
    ScoreState,
    ScrollDownMlbDeckCard,
    ScrollDownMlbDeckResponse,
    TeamSummary,
    ValidationWarning,
    VisualPayload,
)
from .schemas import (
    PlannerReport as DtoPlannerReport,
)
from .validation import validate_no_final_score_leak
from .visual_mapper import classify_runner_style, compute_leverage_tier

__all__ = [
    "built_deck_to_dto",
    "decorate_play_card",
    "scan_response_for_final_score_leaks",
]


def _base_state_dto(state: dict[str, bool]) -> BaseState:
    return BaseState(
        first=bool(state.get("first")),
        second=bool(state.get("second")),
        third=bool(state.get("third")),
    )


def _runner_movements_dto(
    advances: list[RunnerAdvance],
    event_type: str | None,
    runner_names_before: dict[str, str],
    batter_name: str | None,
) -> list[RunnerMovement]:
    out: list[RunnerMovement] = []
    for adv in advances:
        # Resolve the runner's display name.
        if adv.from_base in ("first", "second", "third"):
            name = runner_names_before.get(adv.from_base) or "Runner"
        elif adv.from_base == "home":
            name = batter_name or "Batter"
        else:
            name = "Runner"
        style = classify_runner_style(adv, event_type)
        out.append(
            RunnerMovement(
                runner=name,
                from_base=adv.from_base,
                to_base=adv.to,
                style=(
                    "score"
                    if style == "score"
                    else "out"
                    if style in ("forced_out", "tagged_out", "in_place_out", "double_play")
                    else "advance"
                ),
                out_at=adv.out_at,
            )
        )
    return out


def decorate_play_card(card: BuiltPlayCard) -> None:
    """Compute per-card derived fields (chip label, narrative, leverage tier)."""
    label = result_chip_label(card)
    card.chip_primary = label.primary
    card.chip_secondary = label.secondary
    card.narrative = narrative_for_card(card)
    bases = card.base_state_before
    bases_loaded = bool(
        bases.get("first") and bases.get("second") and bases.get("third")
    )
    card.leverage_tier = compute_leverage_tier(
        inning=card.inning,
        score_before_home=card.score_before_home,
        score_before_away=card.score_before_away,
        score_after_home=card.score_after_home,
        score_after_away=card.score_after_away,
        outs_before=card.outs_before,
        bases_loaded_before=bases_loaded,
    )


def _play_card_dto(card: BuiltPlayCard) -> ScrollDownMlbDeckCard:
    """Convert a BuiltPlayCard to its spoiler-safe DTO. Drops score_after."""
    runs_scored = (
        (card.score_after_home - card.score_before_home)
        + (card.score_after_away - card.score_before_away)
    )

    # Filter runner names to the spoiler-safe per-base map (no batter).
    def _names(src: dict[str, str]) -> dict[str, str]:
        return {
            k: v
            for k, v in src.items()
            if k in ("first", "second", "third") and isinstance(v, str) and v
        }

    play = PlayPayload(
        play_id=str(card.play_index),
        event_type=card.event_type,
        label=card.chip_primary,
        sub_label=card.chip_secondary,
        description=card.narrative or card.description,
        batter_name=card.batter_name,
        pitcher_name=card.pitcher_name,
        balls_before=card.balls_before,
        strikes_before=card.strikes_before,
        outs_before=card.outs_before,
        outs_after=card.outs_after,
        base_state_before=_base_state_dto(card.base_state_before),
        base_state_after=_base_state_dto(card.base_state_after),
        runner_names_before=_names(card.runner_names_before),
        runner_names_after=_names(card.runner_names_after),
        score_before=ScoreState(
            home=card.score_before_home, away=card.score_before_away
        ),
        runs_scored_on_play=max(0, runs_scored),
    )
    visual = VisualPayload(
        trajectory=card.ball_path if card.ball_path not in (None, "none") else None,
        runner_movements=_runner_movements_dto(
            card.advances,
            card.event_type,
            card.runner_names_before,
            card.batter_name,
        ),
        intensity=card.visual_intensity if card.visual_intensity in ("low", "medium", "high") else None,
        animation_profile=card.animation_profile,
    )
    return ScrollDownMlbDeckCard(
        id=f"{card.game_id}-{card.play_index}",
        type=DeckCardType.play,
        sort_order=card.sort_order,
        inning=card.inning,
        half=card.inning_half,
        title=card.inning_label,
        description=card.narrative or card.description,
        play=play,
        visual=visual,
        leverage_tier=card.leverage_tier,
    )


def _scene_card_dto(scene: dict[str, Any], sort_order: int) -> ScrollDownMlbDeckCard:
    return ScrollDownMlbDeckCard(
        id=str(scene.get("cardId", "scene")),
        type=DeckCardType.scene,
        sort_order=sort_order,
        title="First pitch",
        description=(
            f"{scene.get('awayTeam', 'Away')} at {scene.get('homeTeam', 'Home')}"
        ),
    )


def _rhythm_card_dto(card: dict[str, Any], sort_order: int) -> ScrollDownMlbDeckCard:
    kind = card.get("kind", "rhythm")
    dto_kind = DeckCardType.final_setup if kind == "final-setup" else DeckCardType.rhythm
    description = card.get("subtitle") or card.get("label", "")
    to_inning = card.get("toInning")
    to_half = card.get("toHalf")
    return ScrollDownMlbDeckCard(
        id=str(card.get("cardId", f"rhythm-{sort_order}")),
        type=dto_kind,
        sort_order=sort_order,
        inning=to_inning if isinstance(to_inning, int) else None,
        half=to_half if to_half in ("top", "bottom") else None,
        title=card.get("label"),
        description=description,
    )


def built_deck_to_dto(
    *,
    game_id: int,
    deck: list[DeckItem],
    planner_report_entries: list[Any],
    validation_warnings: list[ValidationWarning],
    is_final: bool,
    deck_version: str,
    home_team: TeamSummary | None = None,
    away_team: TeamSummary | None = None,
    last_play_index: int | None = None,
    first_pitch: str | None = None,
    venue: str | None = None,
    home_probable_pitcher: str | None = None,
    away_probable_pitcher: str | None = None,
) -> ScrollDownMlbDeckResponse:
    """Final boundary: convert the built deck to the spoiler-safe DTO.

    Strips post-play score and ensures camelCase wire serialization. The
    final-score-leak detector runs separately via
    `scan_response_for_final_score_leaks` so its findings can flow back
    through `apply_validation_policy` and influence the blocked decision.
    """
    cards: list[ScrollDownMlbDeckCard] = []
    for item in deck:
        if isinstance(item, BuiltPlayCard):
            cards.append(_play_card_dto(item))
        elif isinstance(item, dict):
            kind = item.get("kind")
            if kind == "scene-setter":
                cards.append(_scene_card_dto(item, item.get("index", len(cards))))
            else:
                cards.append(_rhythm_card_dto(item, item.get("index", len(cards))))

    planner_report = DtoPlannerReport(
        rhythm=[
            PlannerNote(
                card_id=e.card_id,
                kind=e.kind,
                reason=e.reason,
                after_play_index=e.after_play_index,
                before_play_index=e.before_play_index,
            )
            for e in planner_report_entries
        ]
    )
    return ScrollDownMlbDeckResponse(
        game_id=str(game_id),
        deck_version=deck_version,
        generated_at=datetime.now(UTC),
        is_final=is_final,
        home_team=home_team,
        away_team=away_team,
        last_play_index=last_play_index,
        first_pitch=first_pitch,
        venue=venue,
        home_probable_pitcher=home_probable_pitcher,
        away_probable_pitcher=away_probable_pitcher,
        cards=cards,
        planner_report=planner_report,
        validation_warnings=validation_warnings,
    )


def scan_response_for_final_score_leaks(
    response: ScrollDownMlbDeckResponse,
) -> list[ValidationWarning]:
    """Scan the serialized wire payload for forbidden final-score keys.

    Returned findings must be merged into the policy decision by the
    caller — they are NOT applied to `response.validation_warnings` here.
    """
    return list(
        validate_no_final_score_leak(
            response.model_dump(mode="json", by_alias=True)
        )
    )
