"""Pydantic schemas for the Scroll Down MLB API.

Spoiler-safety contract (enforced by tests, not just convention):
  * /recent      — no scores, no winners, no final-score fields anywhere.
  * /deck        — pre-reveal: scoreBefore + runsScoredOnPlay only.
                   scoreAfter is intentionally absent from PlayPayload so
                   the final play card cannot leak the final score.
  * /reveal      — the only endpoint allowed to return final score and winner.

All response models expose camelCase field names on the wire via the
`to_camel` alias generator (CI lint gate: scripts/lint_camel_case_schemas.py).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# ---------------------------------------------------------------------------
# Camel-case alias config — every response model in this module uses this.
# ---------------------------------------------------------------------------

_CAMEL = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class TeamSummary(BaseModel):
    """Team identity for spoiler-safe contexts (no scores)."""

    model_config = _CAMEL

    id: str
    abbreviation: str
    display_name: str
    color_light: str | None = None
    color_dark: str | None = None


class BaseState(BaseModel):
    """Whether each base is occupied. Spoiler-safe."""

    model_config = _CAMEL

    first: bool = False
    second: bool = False
    third: bool = False


class ScoreState(BaseModel):
    """Pre-play score snapshot. Used only for `scoreBefore` on play cards."""

    model_config = _CAMEL

    home: int
    away: int


class FinalScore(BaseModel):
    """Final-score payload. Reveal endpoint only."""

    model_config = _CAMEL

    home: int
    away: int


class KeyStat(BaseModel):
    """Reveal-time stat highlight."""

    model_config = _CAMEL

    label: str
    value: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# Validation + planner reporting
# ---------------------------------------------------------------------------


class ValidationSeverity(str, Enum):
    warning = "warning"
    error = "error"


class ValidationWarning(BaseModel):
    """Single validation finding emitted by the deck builder.

    `severity=error` blocks official-deck generation. `severity=warning`
    is non-blocking — live decks ship with warnings, official decks fail.
    """

    model_config = _CAMEL

    code: str
    severity: ValidationSeverity
    message: str
    play_id: str | None = None


class PlannerNote(BaseModel):
    """Why a rhythm card fired (or was suppressed)."""

    model_config = _CAMEL

    card_id: str | None = None
    kind: str
    reason: str
    after_play_index: int | None = None
    before_play_index: int | None = None


class PlannerReport(BaseModel):
    """Per-deck breakdown of pacing decisions. Surfaced for QA, not UX."""

    model_config = _CAMEL

    rhythm: list[PlannerNote] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Visual payload (rendered frontend-side, computed backend-side)
# ---------------------------------------------------------------------------


class RunnerMovement(BaseModel):
    """Single runner traversal on a play card."""

    model_config = _CAMEL

    runner: str
    from_base: Literal["home", "first", "second", "third"] = Field(
        ..., serialization_alias="from", validation_alias="from"
    )
    to_base: Literal["home", "first", "second", "third", "out"] = Field(
        ..., serialization_alias="to", validation_alias="to"
    )
    style: Literal["advance", "score", "out", "hold"] = "advance"
    # Where the runner was tagged when `to == "out"`. Drives the renderer's
    # runner-dot animation: instead of flaring in place, the dot first
    # travels to `outAt` and then flares out there.
    out_at: Literal["first", "second", "third", "home"] | None = None


class VisualPayload(BaseModel):
    """Frontend-safe rendering hints. No game truth derivation needed
    on the client.

    `animationProfile` and `intensity` are precomputed labels — the renderer
    looks them up in its own timing tables. They are spoiler-safe (label
    only, no scores).
    """

    model_config = _CAMEL

    trajectory: str | None = None
    runner_movements: list[RunnerMovement] = Field(default_factory=list)
    intensity: Literal["low", "medium", "high"] | None = None
    animation_profile: str | None = None


# ---------------------------------------------------------------------------
# Play payload — pre-reveal safe
# ---------------------------------------------------------------------------


class PlayPayload(BaseModel):
    """Per-play data attached to a play card.

    Spoiler-safe: `scoreBefore` + `runsScoredOnPlay` are sufficient for the
    renderer to display the running score, and the final play's runs delta
    cannot — by itself — reveal the final score (the user must already
    know `scoreBefore`, which is the running pre-play score).

    NOTE: `scoreAfter` is intentionally absent. If a future renderer needs
    a post-play scoreboard tween, add a derived helper on the frontend
    (`scoreBefore.home + (battingTeam == home ? runs : 0)`) rather than
    surfacing the post-play score on the wire.
    """

    model_config = _CAMEL

    play_id: str
    event_type: str | None = None
    label: str | None = None
    sub_label: str | None = None
    description: str | None = None
    batter_name: str | None = None
    pitcher_name: str | None = None
    balls_before: int | None = None
    strikes_before: int | None = None
    outs_before: int | None = None
    outs_after: int | None = None
    base_state_before: BaseState | None = None
    base_state_after: BaseState | None = None
    # Spoiler-safe per-base runner labels (not the batter — they're in
    # `batterName`). Empty entries mean "no name known."
    runner_names_before: dict[
        Literal["first", "second", "third"], str
    ] = Field(default_factory=dict)
    runner_names_after: dict[
        Literal["first", "second", "third"], str
    ] = Field(default_factory=dict)
    score_before: ScoreState | None = None
    runs_scored_on_play: int = 0


# ---------------------------------------------------------------------------
# Deck cards
# ---------------------------------------------------------------------------


class DeckCardType(str, Enum):
    scene = "scene"
    play = "play"
    rhythm = "rhythm"
    final_setup = "final_setup"


class ScrollDownMlbDeckCard(BaseModel):
    """One card in the deck. Discriminated by `type`."""

    model_config = _CAMEL

    id: str
    type: DeckCardType
    sort_order: int
    inning: int | None = None
    half: Literal["top", "bottom"] | None = None
    title: str | None = None
    description: str
    play: PlayPayload | None = None
    visual: VisualPayload | None = None
    leverage_tier: int | None = None


# ---------------------------------------------------------------------------
# Top-level responses
# ---------------------------------------------------------------------------


class SpoilerPolicy(str, Enum):
    pre_reveal = "pre_reveal"
    post_reveal = "post_reveal"


class ScrollDownMlbDeckResponse(BaseModel):
    """Deck endpoint payload. Spoiler-safe by construction.

    `deckVersion` lets the client detect updates without diffing the cards
    array. The frontend is expected to surface "New moments available" when
    a poll observes a newer version, NOT auto-append cards.

    Team metadata (`homeTeam`, `awayTeam`) is included so the renderer can
    color cards and derive `battingTeamAbbr` from `inning.half` without a
    second fetch. Spoiler-safe — team identity does not reveal the result.
    """

    model_config = _CAMEL

    game_id: str
    deck_version: str
    generated_at: datetime
    is_final: bool
    spoiler_policy: Literal[SpoilerPolicy.pre_reveal] = SpoilerPolicy.pre_reveal
    home_team: TeamSummary | None = None
    away_team: TeamSummary | None = None
    last_play_index: int | None = None
    # Scene metadata — used by the matchup intro card. All spoiler-safe.
    first_pitch: datetime | None = None
    venue: str | None = None
    home_probable_pitcher: str | None = None
    away_probable_pitcher: str | None = None
    cards: list[ScrollDownMlbDeckCard] = Field(default_factory=list)
    planner_report: PlannerReport | None = None
    validation_warnings: list[ValidationWarning] = Field(default_factory=list)


class ScrollDownMlbRecentGame(BaseModel):
    """Spoiler-safe summary for the home feed.

    Notably absent: any score, winner, lead, run totals, or post-final result
    field. `isFinal` is the only progress signal — UX may decide to keep it
    hidden too.
    """

    model_config = _CAMEL

    game_id: str
    league: Literal["MLB"] = "MLB"
    game_date: date | None = None
    status: str | None = None
    status_type: str | None = None
    away_team: TeamSummary
    home_team: TeamSummary
    venue_name: str | None = None
    start_time: datetime | None = None
    has_deck: bool = False
    deck_version: str | None = None
    is_final: bool = False


class ScrollDownMlbRecentResponse(BaseModel):
    model_config = _CAMEL

    games: list[ScrollDownMlbRecentGame] = Field(default_factory=list)


class ScrollDownMlbRevealResponse(BaseModel):
    """Final-score reveal. The ONLY endpoint allowed to expose final score."""

    model_config = _CAMEL

    game_id: str
    final_score: FinalScore
    winner_team_id: str | None = None
    summary: str | None = None
    key_stats: list[KeyStat] = Field(default_factory=list)
    game_flow: list[Any] = Field(default_factory=list)
    generated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Internal/admin payloads (not exposed via public router yet)
# ---------------------------------------------------------------------------


class GenerationPolicy(str, Enum):
    """Validation severity policy by deck kind.

    `live`     — warnings logged, errors degrade gracefully (deck still
                 returned). The user must not see a blank screen mid-game.
    `official` — errors fail closed; the official deck is not produced
                 until the input passes validation cleanly.
    """

    live = "live"
    official = "official"


class GenerationOutcome(BaseModel):
    """Service-layer result of a deck-generation attempt. Internal only."""

    model_config = _CAMEL

    policy: GenerationPolicy
    deck: ScrollDownMlbDeckResponse | None
    warnings: list[ValidationWarning] = Field(default_factory=list)
    errors: list[ValidationWarning] = Field(default_factory=list)
    blocked: bool = False
