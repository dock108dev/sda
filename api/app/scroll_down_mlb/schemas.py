"""Pydantic schemas for MLB timeline reconstruction."""

from __future__ import annotations

from typing import Literal

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


# ---------------------------------------------------------------------------
# Per-event GameSituation snapshots (situationBefore / situationAfter)
# ---------------------------------------------------------------------------


class RunnerSummary(BaseModel):
    """A runner identity for animation continuity and labeling.

    `id` is the upstream player ID when available. When non-null it
    enables cross-card runner keying (otherwise the renderer falls back
    to positional/name slugs). `name` is the normalized display label.
    """

    model_config = _CAMEL

    id: str | None = None
    name: str


class BasesSituation(BaseModel):
    """Runner identity on each base. Spoiler-safe.

    An unoccupied base is `None`. Reading `bases.first is not None`
    is equivalent to the legacy `baseState.first == True`.
    """

    model_config = _CAMEL

    first: RunnerSummary | None = None
    second: RunnerSummary | None = None
    third: RunnerSummary | None = None


class ScoreSituation(BaseModel):
    """Score snapshot. Carried on `situationBefore` only — the post-play
    score is intentionally absent from `situationAfter` so the final
    play card cannot leak the final score."""

    model_config = _CAMEL

    home: int
    away: int


class ScoreChange(BaseModel):
    """Per-team run delta produced by a single event.

    Always present on events; both fields are 0 for non-scoring plays.
    Combined with the already-public pre-play `scoreBefore`, the renderer
    computes the post-play running score locally — the wire never carries
    a cumulative post-play total, so the final play of a completed game
    cannot leak the final score before reveal.
    """

    model_config = _CAMEL

    home: int = 0
    away: int = 0


class CountSituation(BaseModel):
    """Ball/strike count snapshot."""

    model_config = _CAMEL

    balls: int
    strikes: int


class GameSituation(BaseModel):
    """Deterministic per-event game-state snapshot for `situationBefore`.

    `score` is the running pre-play score — safe to ship because it is
    already public from prior cards. The post-play snapshot uses the
    score-less `GameSituationAfter` per the spoiler-safety contract:
    `situationAfter.score` would equal the final score on the last play
    of a completed game and break the pre-reveal contract.
    """

    model_config = _CAMEL

    inning: int
    half: Literal["top", "bottom"]
    outs: int
    score: ScoreSituation | None = None
    count: CountSituation | None = None
    bases: BasesSituation = Field(default_factory=BasesSituation)


class GameSituationAfter(BaseModel):
    """Post-event snapshot. Structurally excludes `score` so the wire
    cannot carry a post-play cumulative total. The renderer computes the
    revealed score locally as `situationBefore.score + scoreChange`.

    Mirrors `GameSituation` field-for-field minus `score`. Splitting the
    type (rather than nulling a shared field) makes the spoiler contract
    a compile-time guarantee instead of a convention.
    """

    model_config = _CAMEL

    inning: int
    half: Literal["top", "bottom"]
    outs: int
    count: CountSituation | None = None
    bases: BasesSituation = Field(default_factory=BasesSituation)


class BaseMovement(BaseModel):
    """One runner's movement on a single event.

    Built deterministically from `situation_before.bases` vs
    `situation_after.bases`, with batter destinations supplied by the
    event context. The frontend's 8-style classifier remains local; the
    backend ships only the coarse 3-style enum (`advance`/`score`/`out`)
    so renderers cannot disagree about which dot moved where.

    `runner` carries the runner's identity for animation continuity.
    `out_at` is the recorded out location when `style == "out"` so the
    renderer can travel the dot to the tag location before flaring.
    """

    model_config = _CAMEL

    runner: RunnerSummary
    from_base: Literal["home", "first", "second", "third"]
    to_base: Literal["home", "first", "second", "third", "out"]
    style: Literal["advance", "score", "out"]
    out_at: Literal["first", "second", "third", "home"] | None = None
    reason: str | None = None


class KeyStat(BaseModel):
    """Reveal-time stat highlight."""

    model_config = _CAMEL

    label: str
    value: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# Per-event result + matchup payloads (consumed by ScrollDownEvent / HalfInningEvent)
# ---------------------------------------------------------------------------


class PlayerSummary(BaseModel):
    """Player identity used in matchup payloads.

    `name` is the normalized display label (`FIRST_INITIAL LAST_NAME`). `id`
    is the upstream player ID when available; non-null `id` enables stable
    cross-card keying for the renderer.
    """

    model_config = _CAMEL

    id: str | None = None
    name: str


class ScrollDownEventResult(BaseModel):
    """Per-event result flags + label/description.

    Replaces ad-hoc event-type string checks scattered in the renderer:
    a single canonical place to ask "is this a hit?", "did the inning end
    here?", "did anyone score?" without re-parsing event_type strings.

    `label` is the chip primary (`"STRIKEOUT"`, `"HOME RUN"`, …) computed
    backend-side. `description` is the humanized play description.
    `is_inning_ending` reflects `situation_after.outs == 3`. `is_scoring_play`
    is `True` when the cumulative run total increased on this play.
    """

    model_config = _CAMEL

    label: str
    description: str
    event_type: str | None = None
    is_out: bool = False
    is_strikeout: bool = False
    is_walk: bool = False
    is_hit: bool = False
    is_scoring_play: bool = False
    is_inning_ending: bool = False


def _empty_event_result() -> ScrollDownEventResult:
    return ScrollDownEventResult(label="", description="")


class ScrollDownEventMatchup(BaseModel):
    """Batter/pitcher at the start of the event. Spoiler-safe.

    Providing reliable `batter` here eliminates the renderer's
    `inferBatterFromMovements()` workaround: the adapter can read
    `matchup.batter.name` directly. Names are normalized per the
    `FIRST_INITIAL LAST_NAME` convention used elsewhere on the wire.
    """

    model_config = _CAMEL

    batter: PlayerSummary | None = None
    pitcher: PlayerSummary | None = None


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


class DisplayHints(BaseModel):
    """Bundled overlay/render hints for a single event.

    Mirrors the renderer's `hasConfidentBattedBallPath` gate so the backend
    can authoritatively suppress overlays for plays whose trajectory is
    non-batted-ball (wild pitch, caught stealing, etc.) without losing the
    underlying zone data. `hit_location` retains the trajectory zone for
    analytics/debug surfaces even when `suppress_movement_lines` is true.
    """

    model_config = _CAMEL

    show_batted_ball_overlay: bool = False
    hit_location: str | None = None
    suppress_movement_lines: bool = False


class VisualPayload(BaseModel):
    """Frontend-safe rendering hints. No game truth derivation needed
    on the client.

    `animationProfile` and `intensity` are precomputed labels — the renderer
    looks them up in its own timing tables. They are spoiler-safe (label
    only, no scores).
    """

    model_config = _CAMEL

    trajectory: str | None = None
    intensity: Literal["low", "medium", "high"] | None = None
    animation_profile: str | None = None
    display_hints: DisplayHints | None = None


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
    # Pitcher's running stat line at this play — already formatted for
    # display, e.g. "4.1 IP · 6 K · 1 BB · 2 R". Backend-formatted so the
    # frontend doesn't need to know the rendering convention. Null when
    # the pitcher of record is unknown for this play.
    pitcher_stat_line: str | None = None
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
    # Per-team breakdown of the run delta. Equal to
    # `(score_after_home - score_before_home, score_after_away - score_before_away)`
    # at build time. Wire-safe: cannot reveal the final score on its own
    # because it is the run delta for THIS play, not a cumulative total.
    score_change: ScoreChange = Field(default_factory=ScoreChange)


# ---------------------------------------------------------------------------
# Half-inning containers (BRAINDUMP: half-inning is the unit of truth)
# ---------------------------------------------------------------------------


class HalfInningEvent(BaseModel):
    """One event within a half-inning container. Spoiler-safe.

    This is the wire-level "ScrollDownEvent" payload — the unit the
    renderer animates. `sequence` is the 1-based position within the
    half-inning. `isSelected` flags whether the deck builder picked the
    play for the curated deck (the full event list is surfaced so the
    renderer can present every play without a second pass over the deck).
    Spoiler contract matches `PlayPayload`: only `scoreBefore` +
    `runsScoredOnPlay` ever appear, never `scoreAfter`.

    `revealType` picks the animation profile family ('pitch' = pitch-level,
    'plate_appearance' = PA-terminal at-bat result, 'play' = multi-runner
    or fielding play). `result` carries canonical boolean flags so the
    renderer never re-parses event_type strings. `matchup` provides
    reliable batter/pitcher identity at the start of the event.
    """

    model_config = _CAMEL

    sequence: int
    play_index: int
    event_type: str | None = None
    outs_before: int | None = None
    outs_after: int | None = None
    base_state_before: BaseState | None = None
    base_state_after: BaseState | None = None
    score_before: ScoreState | None = None
    runs_scored_on_play: int = 0
    # Per-team breakdown of the run delta. The renderer computes the
    # post-play running score locally as `score_before + score_change`
    # so the wire never carries a cumulative post-play total.
    score_change: ScoreChange = Field(default_factory=ScoreChange)
    # Deterministic per-event runner movements derived from
    # `situation_before.bases` vs `situation_after.bases` plus the batter's
    # destination from event context. Held runners (no base change) emit no
    # entry; batter putouts emit no entry (the in-place flare is driven by
    # the animation profile, not a movement record).
    movements: list[BaseMovement] = Field(default_factory=list)
    reveal_type: Literal["pitch", "plate_appearance", "play"] = "play"
    result: ScrollDownEventResult = Field(default_factory=_empty_event_result)
    matchup: ScrollDownEventMatchup = Field(default_factory=ScrollDownEventMatchup)
    is_selected: bool = False


class HalfInningMetaPayload(BaseModel):
    """Per-half summary from the rhythm planner. Wire mirror of the
    internal `HalfInningMeta` dataclass."""

    model_config = _CAMEL

    scored_runs: int = 0
    had_activity: bool = False
    had_lead_change: bool = False
    had_tying: bool = False


class ScrollDownHalfInningContainer(BaseModel):
    """A half-inning grouping holding every event plus a selection overlay.

    The deck (curated subset) and the container (full ordered event list)
    use orthogonal indexing over the same underlying timeline:
    `selectedPlayIndices` projects the deck selection onto this half.
    """

    model_config = _CAMEL

    game_id: str
    inning: int
    half: Literal["top", "bottom"]
    batting_team: TeamSummary
    fielding_team: TeamSummary
    events: list[HalfInningEvent] = Field(default_factory=list)
    meta: HalfInningMetaPayload
    selected_play_indices: list[int] = Field(default_factory=list)
