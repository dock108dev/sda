"""Build cross-sport narrative cards from SDA play-by-play data.

Kept together for now because cache, validation, and response assembly share
ordering invariants; see docs/audits/cleanup-report.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import AsyncSession
from app.db.sports import (
    GameStatus,
    SportsGame,
    SportsGamePlay,
    SportsPlayerBoxscore,
    SportsTeamBoxscore,
)
from app.routers.sports.common import (
    serialize_play_entry,
)
from app.routers.sports.schemas.common import PlayEntry
from app.services.play_importance import (
    DetailContractError,
    enrich_play_importance,
    validate_detail_contract,
)
from app.services.play_tiers import classify_all_tiers, enrich_play_entries

from .assembly import (
    SUPPORTED_SPORTS,
    _initial_status,
    _league_code,
    _plays_through,
    _provider_source_play_id,
    _response,
    _situation,
    _source_hash_for_card_feed,
    _source_play_id,
    _state_issues,
    _team_for_play,
)
from .basketball_context import (
    BasketballCardContext,
    build_basketball_card_contexts,
)
from .context_helpers import impact_for, score_after_for, score_before_for, score_change_for
from .debug import (
    cache_state,
    debug_findings,
    debug_reason,
    debug_status,
)
from .debug_schemas import CardGenerationDebugResponse
from .football_context import (
    FootballCardContext,
    build_football_card_contexts,
)
from .mlb_context import MlbCardContext, build_mlb_card_contexts
from .narrative import (
    card_headline,
    card_tags,
    content_depth,
    important_narrative,
    lead_in,
    play_detail,
    render_type,
    score_display,
    situation_display,
    stage_setting,
    team_context,
    visual_importance,
)
from .narrative_validation import issue_codes
from .narrative_validation_service import CardValidationOutcome, validate_feed_cards
from .nhl_context import NhlCardContext, build_nhl_card_contexts
from .schemas import (
    CardFeedResponse,
    CardFeedStatus,
    CardPeriod,
    NarrativeCard,
)
from .section_leadins import build_section_lead_ins

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class _CardFeedBuildResult:
    response: CardFeedResponse
    source_hash: str
    policy: Literal["live", "official"]
    validation_outcomes: tuple[CardValidationOutcome, ...] = ()
    detail_contract_error: str | None = None
    generation_error_type: str | None = None



async def get_game_card_feed(
    session: AsyncSession,
    game_id: int,
    through_play_index: int | None = None,
) -> CardFeedResponse:
    """Return the persisted normalized narrative-card feed for one game."""
    if through_play_index is None:
        from .materialization import get_or_materialize_card_feed

        return await get_or_materialize_card_feed(session, game_id)

    # Partial feed windows are debug/admin-only; keep them generated directly
    # rather than creating separate persisted artifacts for each boundary.
    result = await session.execute(
        select(SportsGame)
        .options(*card_feed_game_options())
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return build_card_feed_from_game(
        game,
        through_play_index=through_play_index,
    )


async def get_game_card_generation_debug(
    session: AsyncSession,
    game_id: int,
    through_play_index: int | None = None,
    *,
    include_feed: bool = True,
) -> CardGenerationDebugResponse:
    """Load one game and return its card-generation debug envelope."""
    result = await session.execute(
        select(SportsGame)
        .options(*card_feed_game_options())
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return build_card_generation_debug_from_game(
        game,
        through_play_index=through_play_index,
        include_feed=include_feed,
    )


def build_card_feed_from_game(
    game: SportsGame,
    through_play_index: int | None = None,
) -> CardFeedResponse:
    """Build the renderable feed envelope from a loaded game object."""
    return _build_card_feed_result(
        game,
        through_play_index=through_play_index,
    ).response


def build_card_generation_debug_from_game(
    game: SportsGame,
    through_play_index: int | None = None,
    *,
    include_feed: bool = True,
) -> CardGenerationDebugResponse:
    """Build an admin/debug envelope for cross-sport narrative cards."""
    result = _build_card_feed_result(
        game,
        through_play_index=through_play_index,
    )
    response = result.response
    warnings, errors = debug_findings(result)
    status = debug_status(response)
    available = status == "available"
    reason = debug_reason(response, result, status)
    generation_version = (
        f"cards-v{response.contract_version}-{result.policy}-{result.source_hash}"
        if result.source_hash
        else None
    )

    return CardGenerationDebugResponse(
        available=available,
        status=status,
        reason=reason,
        policy=result.policy,
        card_count=response.generation.card_count,
        last_play_index=response.generation.last_play_index,
        generation_version=generation_version,
        source_hash=result.source_hash,
        cache_state=cache_state(response),
        warnings=warnings,
        errors=errors,
        feed=(
            response.model_dump(by_alias=True, mode="json", exclude_none=True)
            if include_feed
            else None
        ),
    )


def card_feed_game_options():
    """Eager-load every relationship the card feed builder reads."""
    return (
        selectinload(SportsGame.league),
        selectinload(SportsGame.home_team),
        selectinload(SportsGame.away_team),
        selectinload(SportsGame.team_boxscores).selectinload(SportsTeamBoxscore.team),
        selectinload(SportsGame.player_boxscores).selectinload(SportsPlayerBoxscore.team),
        selectinload(SportsGame.plays).selectinload(SportsGamePlay.team),
    )


def _build_card_feed_result(
    game: SportsGame,
    through_play_index: int | None = None,
) -> _CardFeedBuildResult:
    league = _league_code(game)
    sport = SUPPORTED_SPORTS.get(league, "unknown")
    all_plays = sorted(list(game.plays or []), key=lambda play: play.play_index)
    sorted_plays = _plays_through(all_plays, through_play_index)
    last_play_index = sorted_plays[-1].play_index if sorted_plays else None
    initial_status = _initial_status(game, league, sorted_plays)
    source_hash = _source_hash_for_card_feed(game, league, sorted_plays)
    policy: Literal["live", "official"] = (
        "official" if GameStatus.is_final_or_post_final_status(game.status) else "live"
    )

    if initial_status in {
        CardFeedStatus.unsupported_sport,
        CardFeedStatus.no_pbp_yet,
        CardFeedStatus.generation_pending,
        CardFeedStatus.validation_blocked,
    }:
        return _CardFeedBuildResult(
            response=_response(
                game=game,
                sport=sport,
                league=league,
                feed_status=initial_status,
                cards=[],
                last_play_index=last_play_index,
                validation_issues=_state_issues(initial_status),
            ),
            source_hash=source_hash,
            policy=policy,
        )

    try:
        plays = _enriched_plays(game, sorted_plays, league)
    except DetailContractError as exc:
        logger.warning("feed_card_validation_blocked", extra={"game_id": game.id})
        return _CardFeedBuildResult(
            response=_response(
                game=game,
                sport=sport,
                league=league,
                feed_status=CardFeedStatus.validation_blocked,
                cards=[],
                last_play_index=last_play_index,
                validation_issues=[str(exc)],
            ),
            source_hash=source_hash,
            policy=policy,
            detail_contract_error=str(exc),
        )
    except Exception as exc:
        logger.exception("feed_card_generation_failed", extra={"game_id": game.id})
        return _CardFeedBuildResult(
            response=_response(
                game=game,
                sport=sport,
                league=league,
                feed_status=CardFeedStatus.validation_blocked,
                cards=[],
                last_play_index=last_play_index,
                validation_issues=[f"Card generation failed: {type(exc).__name__}"],
            ),
            source_hash=source_hash,
            policy=policy,
            generation_error_type=type(exc).__name__,
        )

    mlb_contexts = (
        build_mlb_card_contexts(game, sorted_plays) if league == "MLB" else {}
    )
    nhl_contexts = build_nhl_card_contexts(game, plays) if league == "NHL" else {}
    basketball_contexts = (
        build_basketball_card_contexts(game, plays)
        if league in {"NBA", "NCAAB"}
        else {}
    )
    football_contexts = (
        build_football_card_contexts(game, plays, sorted_plays)
        if league in {"NFL", "NCAAF"}
        else {}
    )
    source_play_ids = {
        play.play_index: _provider_source_play_id(play)
        for play in sorted_plays
    }
    cards = [
        _card_from_play(
            game=game,
            play=play,
            sport=sport,
            league=league,
            source_play_id=source_play_ids.get(play.play_index),
            mlb_context=mlb_contexts.get(play.play_index),
            nhl_context=nhl_contexts.get(play.play_index),
            basketball_context=basketball_contexts.get(play.play_index),
            football_context=football_contexts.get(play.play_index),
        )
        for play in plays
    ]
    validation_outcomes = validate_feed_cards(
        game=game,
        sorted_plays=sorted_plays,
        cards=cards,
    )
    validation_findings = [finding for outcome in validation_outcomes for finding in outcome.findings]
    validation_issues = issue_codes(validation_findings)
    if any(outcome.card is None for outcome in validation_outcomes):
        logger.warning(
            "feed_card_public_dto_validation_blocked",
            extra={"game_id": game.id, "validation_issues": validation_issues},
        )
        return _CardFeedBuildResult(
            response=_response(
                game=game,
                sport=sport,
                league=league,
                feed_status=CardFeedStatus.validation_blocked,
                cards=[],
                last_play_index=last_play_index,
                validation_issues=validation_issues,
            ),
            source_hash=source_hash,
            policy=policy,
            validation_outcomes=tuple(validation_outcomes),
        )
    if validation_issues:
        logger.warning("feed_card_text_validation_fallback", extra={"game_id": game.id, "validation_issues": validation_issues})
    validated_cards = [outcome.card for outcome in validation_outcomes if outcome.card is not None]
    return _CardFeedBuildResult(
            response=_response(
                game=game,
                sport=sport,
                league=league,
                feed_status=initial_status,
                cards=validated_cards,
                last_play_index=last_play_index,
                sections=build_section_lead_ins(validated_cards),
                validation_issues=validation_issues,
            ),
        source_hash=source_hash,
        policy=policy,
        validation_outcomes=tuple(validation_outcomes),
    )


def _enriched_plays(
    game: SportsGame,
    sorted_plays: list[SportsGamePlay],
    league: str,
) -> list[PlayEntry]:
    home_abbr = game.home_team.abbreviation if game.home_team else None
    away_abbr = game.away_team.abbreviation if game.away_team else None
    if not home_abbr or not away_abbr:
        raise DetailContractError("team abbreviations missing")

    plays = [serialize_play_entry(play, league) for play in sorted_plays]
    tiers = classify_all_tiers(plays, league)
    for entry, tier in zip(plays, tiers, strict=False):
        entry.tier = tier
    enrich_play_entries(plays, league, home_abbr, away_abbr)
    enrich_play_importance(plays, league_code=league, home_abbr=home_abbr, away_abbr=away_abbr)
    validate_detail_contract(plays)
    return plays


def _card_from_play(
    *,
    game: SportsGame,
    play: PlayEntry,
    sport: str,
    league: str,
    source_play_id: str | None = None,
    mlb_context: MlbCardContext | None = None,
    nhl_context: NhlCardContext | None = None,
    basketball_context: BasketballCardContext | None = None,
    football_context: FootballCardContext | None = None,
) -> NarrativeCard:
    tier = play.tier or 3
    context = mlb_context or nhl_context or basketball_context or football_context
    impact_context = nhl_context or basketball_context or football_context
    score_change = score_change_for(play, context)
    description = play_detail(play)
    content_depth_value = content_depth(play)
    lead_in_value = lead_in(play)
    stage_setting_value = stage_setting(play, context)
    tags = card_tags(play, content_depth_value)
    if play.mode_eligibility is None:
        raise DetailContractError("modeEligibility missing")
    if play.importance is None:
        raise DetailContractError("importance missing")
    impact = impact_for(play, score_change, impact_context)
    team = _team_for_play(game, play.team_abbreviation)
    render_type_value = render_type(play)
    narrative = (
        important_narrative(
            game=game,
            play=play,
            team=team,
            context=context,
            score_change=score_change,
            description=description,
            impact=impact,
        )
        if render_type_value == "important_narrative"
        else None
    )
    if render_type_value == "important_narrative" and narrative is None:
        raise DetailContractError(
            f"important narrative fields missing for play {play.play_index}"
        )
    card = NarrativeCard(
        id=f"{game.id}:{play.play_index}",
        gameId=game.id,
        sourcePlayId=_source_play_id(play, football_context, source_play_id),
        playIndex=play.play_index,
        sport=sport,
        league=league,
        tier=tier,
        contentDepth=content_depth_value,
        modeEligibility=play.mode_eligibility,
        importance=play.importance,
        renderType=render_type_value,
        visualImportance=visual_importance(play),
        periodLabel=play.period_label,
        period=CardPeriod(ordinal=play.quarter, label=play.period_label, type=play.period_type),
        displayTime=play.time_label or play.clock_label or play.period_label,
        clock=play.game_clock,
        team=team,
        teamDisplay=team.name or team.abbreviation,
        teamContext=team_context(league, play, team, context),
        scoreBefore=score_before_for(play, context),
        scoreChange=score_change,
        scoreAfter=score_after_for(play, context),
        scoreBeforeDisplay=score_display(
            game=game,
            team=team,
            score=score_before_for(play, context),
        ),
        scoreAfterDisplay=score_display(
            game=game,
            team=team,
            score=score_after_for(play, context),
        ),
        situationBeforeDisplay=situation_display(context, before=True),
        situationAfterDisplay=situation_display(context, before=False),
        situation=_situation(
            play,
            mlb_context,
            nhl_context,
            basketball_context,
            football_context,
        ),
        leadIn=lead_in_value,
        stageSetting=stage_setting_value,
        headline=card_headline(play),
        description=description,
        setupLine=narrative.setup_line if narrative else None,
        playLine=narrative.play_line if narrative else None,
        updateLine=narrative.update_line if narrative else None,
        rawPlayText=description,
        eventType=play.display_type or play.play_type,
        fullDetails=None,
        impact=impact,
        tags=tags,
    )
    return card
