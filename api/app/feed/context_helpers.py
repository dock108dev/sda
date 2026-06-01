"""Shared context dispatch helpers for feed card assembly."""

from __future__ import annotations

from app.routers.sports.schemas.common import PlayEntry, ScoreObject

from .basketball_context import BasketballCardContext
from .football_context import FootballCardContext
from .mlb_context import MlbCardContext
from .nhl_context import NhlCardContext
from .schemas import ScoreChange, SpoilerPolicy

CardContext = MlbCardContext | NhlCardContext | BasketballCardContext | FootballCardContext


def score_change_for(play: PlayEntry, context: CardContext | None) -> ScoreChange:
    """Return adapter-owned score delta, falling back to play snapshots."""
    if context is not None:
        return context.score_change
    before = play.score_before
    after = play.score_after
    if not before or not after:
        return ScoreChange()
    return ScoreChange(home=max(0, after.home - before.home), away=max(0, after.away - before.away))


def score_before_for(play: PlayEntry, context: CardContext | None) -> ScoreObject | None:
    """Return adapter-owned score-before snapshot when available."""
    if context is not None:
        return context.score_before
    return play.score_before


def score_after_for(
    play: PlayEntry,
    spoiler_policy: SpoilerPolicy,
    context: CardContext | None,
) -> ScoreObject | None:
    """Return score-after only when the caller requested revealed scores."""
    if spoiler_policy is not SpoilerPolicy.revealed:
        return None
    if context is not None:
        return context.score_after
    return play.score_after


def impact_for(
    play: PlayEntry,
    score_change: ScoreChange,
    context: NhlCardContext | BasketballCardContext | FootballCardContext | None,
) -> str | None:
    """Return sport-adapter impact, falling back to generic play impact."""
    if context is not None:
        return context.impact
    if score_change.home or score_change.away:
        units = score_change.home + score_change.away
        team = play.scoring_team_abbr or play.team_abbreviation
        return f"{team} scores {units}" if team else f"Scoring play: {units}"
    importance = play.importance
    if not importance:
        return None
    if importance.is_lead_change:
        return "Lead change"
    if importance.is_tying_play:
        return "Tying play"
    if importance.is_final_play:
        return "Final play"
    if importance.is_run_ending:
        return "Run ending play"
    if importance.is_key_moment:
        return "Key moment"
    return None
