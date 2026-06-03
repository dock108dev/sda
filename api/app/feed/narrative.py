"""Narrative text and render helpers for normalized card feed cards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.db.sports import SportsGame
from app.routers.sports.schemas.common import PlayEntry

from .basketball_context import BasketballCardContext
from .context_helpers import score_after_for, score_before_for
from .football_context import FootballCardContext
from .mlb_context import MlbCardContext
from .nhl_context import NhlCardContext
from .schemas import CardTeam, ScoreChange


@dataclass(frozen=True)
class _ImportantNarrative:
    setup_line: str
    play_line: str
    update_line: str


def lead_in(play: PlayEntry) -> str:
    label = (play.time_label or play.period_label or play.clock_label or "").strip()
    return label or "Game event"


def stage_setting(
    play: PlayEntry,
    context: MlbCardContext | NhlCardContext | BasketballCardContext | FootballCardContext | None,
) -> str:
    if isinstance(context, MlbCardContext):
        base_out = context.raw.get("baseOut") if isinstance(context.raw, dict) else {}
        period = context.raw.get("period") if isinstance(context.raw, dict) else {}
        pieces = [
            period.get("label") if isinstance(period, dict) else None,
            base_out.get("baseStateBefore") if isinstance(base_out, dict) else None,
            base_out.get("outsBefore") if isinstance(base_out, dict) else None,
        ]
        label = ", ".join(
            f"{piece} outs" if isinstance(piece, int) else piece
            for piece in pieces
            if piece is not None and piece != ""
        )
        if label:
            return label
    if isinstance(context, NhlCardContext):
        label = nhl_stage_setting(context)
        if label:
            return label
    if isinstance(context, BasketballCardContext):
        label = basketball_stage_setting(context)
        if label:
            return label
    if context and context.summary:
        return context.summary
    return lead_in(play)


def render_type(
    play: PlayEntry,
) -> Literal["important_narrative", "standard_pbp", "full_pbp"]:
    if play.mode_eligibility and play.mode_eligibility.important:
        return "important_narrative"
    if play.mode_eligibility and play.mode_eligibility.standard:
        return "standard_pbp"
    return "full_pbp"


def important_narrative(
    *,
    game: SportsGame,
    play: PlayEntry,
    team: CardTeam,
    context: MlbCardContext | NhlCardContext | BasketballCardContext | FootballCardContext | None,
    score_change: ScoreChange,
    description: str,
    impact: str | None,
) -> _ImportantNarrative | None:
    setup = _important_setup_line(game=game, play=play, team=team, context=context)
    play_line = _sentence(description)
    update = _important_update_line(
        game=game,
        play=play,
        team=team,
        context=context,
        score_change=score_change,
        impact=impact,
    )
    if not setup or not play_line or not update:
        return None
    return _ImportantNarrative(
        setup_line=setup,
        play_line=play_line,
        update_line=update,
    )


def _important_setup_line(
    *,
    game: SportsGame,
    play: PlayEntry,
    team: CardTeam,
    context: MlbCardContext | NhlCardContext | BasketballCardContext | FootballCardContext | None,
) -> str | None:
    score = score_display(game=game, team=team, score=score_before_for(play, context))
    situation = situation_display(context, before=True)
    if isinstance(context, NhlCardContext):
        strength = _nhl_strength_text(context)
        pieces = [score, strength, situation]
        return _sentence(", ".join(piece for piece in pieces if piece))
    if isinstance(context, BasketballCardContext):
        pieces = [score, situation]
        return _sentence(", ".join(piece for piece in pieces if piece))
    if isinstance(context, FootballCardContext):
        pieces = [score, situation]
        return _sentence(", ".join(piece for piece in pieces if piece))
    pieces = [score, situation]
    return _sentence(", ".join(piece for piece in pieces if piece))


def _important_update_line(
    *,
    game: SportsGame,
    play: PlayEntry,
    team: CardTeam,
    context: MlbCardContext | NhlCardContext | BasketballCardContext | FootballCardContext | None,
    score_change: ScoreChange,
    impact: str | None,
) -> str | None:
    scoring = _score_change_text(team=team, score_change=score_change)
    score_after = score_display(
        game=game,
        team=team,
        score=score_after_for(play, context),
    )
    situation_after = situation_display(context, before=False)
    if scoring:
        return _sentence(
            ". ".join(
                piece for piece in [scoring, score_after, situation_after] if piece
            )
        )
    if impact and impact != "none":
        return _sentence(_tag_label(impact))
    return _sentence(situation_after or "Play complete")


def _sentence(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    return text if text.endswith((".", "!", "?")) else f"{text}."


def team_context(
    league: str,
    play: PlayEntry,
    team: CardTeam,
    context: MlbCardContext | NhlCardContext | BasketballCardContext | FootballCardContext | None,
) -> str | None:
    abbr = team.abbreviation or play.team_abbreviation
    if not abbr:
        return None
    if league == "MLB":
        return f"{abbr} batting"
    if isinstance(context, NhlCardContext):
        strength = _nhl_strength_text(context)
        return f"{abbr} {strength}" if strength else abbr
    return abbr


def score_display(
    *,
    game: SportsGame,
    team: CardTeam,
    score: Any,
) -> str | None:
    if score is None:
        return None
    home = getattr(score, "home", None)
    away = getattr(score, "away", None)
    if not isinstance(home, int) or not isinstance(away, int):
        return None
    team_label = team.abbreviation or team.name or "Team"
    if team.side == "home":
        own, opp = home, away
    elif team.side == "away":
        own, opp = away, home
    else:
        away_abbr = game.away_team.abbreviation if game.away_team else "Away"
        home_abbr = game.home_team.abbreviation if game.home_team else "Home"
        return f"{away_abbr} {away}, {home_abbr} {home}"
    if own > opp:
        return f"{team_label} up {own}-{opp}"
    if own < opp:
        return f"{team_label} down {opp}-{own}"
    return f"{team_label} tied {own}-{opp}"


def _score_change_text(*, team: CardTeam, score_change: ScoreChange) -> str | None:
    runs = 0
    if team.side == "home":
        runs = score_change.home
    elif team.side == "away":
        runs = score_change.away
    else:
        runs = max(score_change.home, score_change.away)
    if runs <= 0:
        return None
    label = team.abbreviation or team.name or "Team"
    unit = "run" if runs == 1 else "runs"
    return f"{label} scores {runs} {unit}"


def situation_display(
    context: MlbCardContext | NhlCardContext | BasketballCardContext | FootballCardContext | None,
    *,
    before: bool,
) -> str | None:
    if isinstance(context, MlbCardContext):
        base_out = context.raw.get("baseOut") if isinstance(context.raw, dict) else {}
        if isinstance(base_out, dict):
            base_state = base_out.get("baseStateBefore" if before else "baseStateAfter")
            outs = base_out.get("outsBefore" if before else "outsAfter")
            pieces = [
                _lower_initial(str(base_state)) if base_state else None,
                _outs_display(outs) if isinstance(outs, int) and outs < 3 else None,
            ]
            return ", ".join(piece for piece in pieces if piece) or None
    if isinstance(context, NhlCardContext):
        raw = context.raw if isinstance(context.raw, dict) else {}
        clock = raw.get("clock") if isinstance(raw.get("clock"), dict) else {}
        label = clock.get("label") or clock.get("gameClock")
        return str(label) if label else None
    if isinstance(context, BasketballCardContext):
        raw = context.raw if isinstance(context.raw, dict) else {}
        clock = raw.get("clock") if isinstance(raw.get("clock"), dict) else {}
        label = clock.get("label") or clock.get("gameClock")
        return str(label) if label else None
    if isinstance(context, FootballCardContext):
        return context.summary
    return context.summary if context else None


def _outs_display(outs: int) -> str:
    if outs == 0:
        return "nobody out"
    if outs == 1:
        return "1 out"
    return f"{outs} outs"


def _lower_initial(value: str) -> str:
    return value[:1].lower() + value[1:] if value else value


def _nhl_strength_text(context: NhlCardContext) -> str | None:
    raw = context.raw if isinstance(context.raw, dict) else {}
    strength = raw.get("strength") if isinstance(raw.get("strength"), dict) else {}
    state = strength.get("state")
    if not state:
        return None
    return str(state).replace("_", " ")


def full_details(
    context: MlbCardContext | NhlCardContext | BasketballCardContext | FootballCardContext | None,
) -> dict[str, Any] | None:
    if context is None:
        return None
    return context.raw if isinstance(context.raw, dict) else None


def nhl_stage_setting(context: NhlCardContext) -> str | None:
    raw = context.raw if isinstance(context.raw, dict) else {}
    clock = raw.get("clock") if isinstance(raw.get("clock"), dict) else {}
    strength = raw.get("strength") if isinstance(raw.get("strength"), dict) else {}
    event = raw.get("event") if isinstance(raw.get("event"), dict) else {}
    pieces = [
        clock.get("label") or clock.get("gameClock"),
        str(strength.get("state")).replace("_", " ") if strength.get("state") else None,
        str(event.get("type")).replace("_", " ") if event.get("type") else None,
    ]
    label = ", ".join(piece for piece in pieces if piece)
    return label or None


def basketball_stage_setting(context: BasketballCardContext) -> str | None:
    raw = context.raw if isinstance(context.raw, dict) else {}
    clock = raw.get("clock") if isinstance(raw.get("clock"), dict) else {}
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    result_label = result.get("displayType") or result.get("type") or result.get("family")
    pieces = [
        clock.get("label") or clock.get("gameClock"),
        str(result_label).replace("_", " ") if result_label else None,
    ]
    label = ", ".join(piece for piece in pieces if piece)
    return label or None


def card_headline(play: PlayEntry) -> str:
    if play.player_name and play.display_type:
        return f"{play.player_name} - {play.display_type}"
    return play.display_type or play.play_type or "Play"


def card_tags(play: PlayEntry, content_depth: str) -> list[str]:
    tags: list[str] = []
    if play.display_type:
        tags.append(play.display_type)
    if play.importance:
        tags.extend(_tag_label(reason) for reason in play.importance.reasons)
    limit = {"extended": 5, "standard": 3, "brief": 2}[content_depth]
    return list(dict.fromkeys(tag for tag in tags if tag))[:limit]


def play_detail(play: PlayEntry) -> str:
    description = clean_text(play.description)
    if description and not _looks_like_raw_feed_text(description):
        return description
    return play.display_type or "Play"


def clean_text(value: str | None) -> str:
    cleaned = (value or "").replace(" 's", "'s")
    cleaned = re.sub(r"\[([^\]]*)\]", r"(\1)", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _looks_like_raw_feed_text(value: str) -> bool:
    token = value.strip()
    if not token:
        return True
    return "_" in token and token.upper() == token


def _tag_label(value: str) -> str:
    return value.replace("-", " ").strip().capitalize()


def visual_importance(play: PlayEntry) -> str:
    importance = play.importance
    if importance is None:
        return "low"
    if importance.is_lead_change or importance.is_tying_play:
        return "critical"
    if importance.level == "primary":
        return "high"
    if importance.level == "secondary" or importance.is_scoring_play:
        return "medium"
    return "low"


def content_depth(play: PlayEntry) -> str:
    importance = play.importance
    if importance is None:
        return {1: "extended", 2: "standard"}.get(play.tier or 3, "brief")
    if (
        importance.is_lead_change
        or importance.is_tying_play
        or importance.is_final_play
        or importance.is_run_ending
        or importance.level == "primary"
    ):
        return "extended"
    if importance.is_scoring_play or importance.level == "secondary":
        return "standard"
    return {1: "extended", 2: "standard"}.get(play.tier or 3, "brief")
