"""Build cross-sport narrative cards from SDA play-by-play data.

Kept together for now because cache, validation, redaction, and response
assembly share ordering invariants; see docs/audits/cleanup-report.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import AsyncSession
from app.db.sports import GameStatus, SportsGame, SportsGamePlay
from app.routers.sports.common import serialize_play_entry
from app.routers.sports.schemas.common import PlayEntry
from app.services.play_importance import (
    DetailContractError,
    enrich_play_importance,
    validate_detail_contract,
)
from app.services.play_tiers import classify_all_tiers, enrich_play_entries

from .basketball_context import (
    BasketballCardContext,
    build_basketball_card_contexts,
)
from .context_helpers import impact_for, score_after_for, score_before_for, score_change_for
from .debug_schemas import CardGenerationDebugFinding, CardGenerationDebugResponse
from .football_context import (
    FootballCardContext,
    build_football_card_contexts,
)
from .mlb_context import MlbCardContext, build_mlb_card_contexts
from .narrative_validation import issue_codes
from .narrative_validation_service import CardValidationOutcome, validate_feed_cards
from .nhl_context import NhlCardContext, build_nhl_card_contexts
from .schemas import (
    CardFeedResponse,
    CardFeedStatus,
    CardFieldSpoilerLevel,
    CardGameMetadata,
    CardPeriod,
    CardSectionLeadIn,
    CardSituation,
    CardTeam,
    CardTextSpoilerLevels,
    CompletedGameRevealBoundary,
    FeedGenerationStatus,
    NarrativeCard,
    RevealAvailability,
    ScoreChange,
    SpoilerPolicy,
)
from .section_leadins import build_section_lead_ins

logger = logging.getLogger(__name__)

_SUPPORTED_SPORTS: dict[str, str] = {
    "MLB": "baseball",
    "NHL": "hockey",
    "NBA": "basketball",
    "NCAAB": "basketball",
    "NFL": "football",
    "NCAAF": "football",
}

_REVEAL_ONLY_IMPACTS = frozenset(
    {
        "lead_change",
        "tying",
        "go_ahead",
        "clutch_score",
        "scoring_run",
        "empty_net_goal",
    }
)
_REVEAL_ONLY_TAG_PARTS = (
    "lead",
    "tying",
    "tie",
    "go ahead",
    "go-ahead",
    "clutch",
    "run ending",
)
_REVEAL_ONLY_RAW_KEYS = frozenset(
    {
        "lead",
        "clutch",
        "run",
        "leaderbefore",
        "leaderafter",
        "marginbefore",
        "marginafter",
        "margin",
        "startscore",
        "endscore",
        "isleadchange",
        "istyingplay",
        "isgoaheadplay",
        "isgoahead",
        "isrunending",
        "isclutch",
        "islategame",
        "isemptynet",
    }
)


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
    spoiler_policy: SpoilerPolicy,
    through_play_index: int | None = None,
) -> CardFeedResponse:
    """Load one game and return its normalized narrative-card feed."""
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.plays).selectinload(SportsGamePlay.team),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return build_card_feed_from_game(
        game,
        spoiler_policy,
        through_play_index=through_play_index,
    )


async def get_game_card_generation_debug(
    session: AsyncSession,
    game_id: int,
    spoiler_policy: SpoilerPolicy,
    through_play_index: int | None = None,
    *,
    include_feed: bool = True,
) -> CardGenerationDebugResponse:
    """Load one game and return its card-generation debug envelope."""
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.plays).selectinload(SportsGamePlay.team),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return build_card_generation_debug_from_game(
        game,
        spoiler_policy,
        through_play_index=through_play_index,
        include_feed=include_feed,
    )


def build_card_feed_from_game(
    game: SportsGame,
    spoiler_policy: SpoilerPolicy,
    through_play_index: int | None = None,
) -> CardFeedResponse:
    """Build the renderable feed envelope from a loaded game object."""
    return _build_card_feed_result(
        game,
        spoiler_policy,
        through_play_index=through_play_index,
    ).response


def build_card_generation_debug_from_game(
    game: SportsGame,
    spoiler_policy: SpoilerPolicy,
    through_play_index: int | None = None,
    *,
    include_feed: bool = True,
) -> CardGenerationDebugResponse:
    """Build an admin/debug envelope for cross-sport narrative cards."""
    result = _build_card_feed_result(
        game,
        spoiler_policy,
        through_play_index=through_play_index,
    )
    response = result.response
    warnings, errors = _debug_findings(result)
    status = _debug_status(response)
    available = status == "available"
    reason = _debug_reason(response, result, status)
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
        cache_state=_cache_state(response),
        warnings=warnings,
        errors=errors,
        feed=(
            response.model_dump(by_alias=True, mode="json", exclude_none=True)
            if include_feed
            else None
        ),
    )


def _build_card_feed_result(
    game: SportsGame,
    spoiler_policy: SpoilerPolicy,
    through_play_index: int | None = None,
) -> _CardFeedBuildResult:
    league = _league_code(game)
    sport = _SUPPORTED_SPORTS.get(league, "unknown")
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
                spoiler_policy=spoiler_policy,
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
                spoiler_policy=spoiler_policy,
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
                spoiler_policy=spoiler_policy,
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
            spoiler_policy=spoiler_policy,
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
        spoiler_policy=spoiler_policy,
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
                spoiler_policy=spoiler_policy,
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
                spoiler_policy=spoiler_policy,
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


def _debug_findings(
    result: _CardFeedBuildResult,
) -> tuple[list[CardGenerationDebugFinding], list[CardGenerationDebugFinding]]:
    warnings: list[CardGenerationDebugFinding] = []
    errors: list[CardGenerationDebugFinding] = []

    response = result.response
    if response.generation.status is CardFeedStatus.stale_regenerating:
        warnings.append(
            _debug_finding(
                code="live_generation_stale_regenerating",
                severity="warning",
                message="Live game cards are available while regeneration is pending.",
                scope="cache",
            )
        )

    if result.detail_contract_error is not None:
        errors.append(
            _debug_finding(
                code="detail_contract_invalid",
                severity="error",
                message=result.detail_contract_error,
                scope="sport_adapter",
            )
        )

    if result.generation_error_type is not None:
        errors.append(
            _debug_finding(
                code="card_generation_failed",
                severity="error",
                message=f"Card generation failed: {result.generation_error_type}",
                scope="generation",
            )
        )

    if (
        response.generation.status is CardFeedStatus.validation_blocked
        and not errors
        and not result.validation_outcomes
    ):
        errors.append(
            _debug_finding(
                code="card_generation_blocked",
                severity="error",
                message=response.generation.validation_issues[0]
                if response.generation.validation_issues
                else "Card generation is blocked by game state.",
                scope="generation",
            )
        )

    for outcome in result.validation_outcomes:
        for finding in outcome.findings:
            target = errors if finding.severity == "error" else warnings
            target.append(
                _debug_finding(
                    code=finding.code,
                    severity=finding.severity,
                    message=finding.message,
                    play_id=outcome.play_id or str(outcome.play_index),
                    scope=(
                        "serialized"
                        if finding.code == "public_card_forbidden_key"
                        else _finding_scope(finding.field)
                    ),
                )
            )

    return warnings, errors


def _debug_finding(
    *,
    code: str,
    severity: Literal["info", "warning", "error"],
    message: str,
    play_id: str | None = None,
    scope: str | None = None,
) -> CardGenerationDebugFinding:
    return CardGenerationDebugFinding(
        code=code,
        severity=severity,
        message=message,
        play_id=play_id,
        scope=scope,
    )


def _finding_scope(field: str | None) -> str:
    if field is None:
        return "card"
    if field.startswith("cards."):
        return "serialized"
    if "." in field:
        return field
    return f"card.{field}"


def _debug_status(
    response: CardFeedResponse,
) -> Literal["available", "not_available", "blocked"]:
    if response.generation.status in {
        CardFeedStatus.ready,
        CardFeedStatus.stale_regenerating,
    }:
        return "available"
    if response.generation.status is CardFeedStatus.validation_blocked:
        return "blocked"
    return "not_available"


def _debug_reason(
    response: CardFeedResponse,
    result: _CardFeedBuildResult,
    status: Literal["available", "not_available", "blocked"],
) -> str | None:
    if status == "available":
        if response.generation.status is CardFeedStatus.stale_regenerating:
            return "Live cards are available from the current source while updates regenerate."
        return None
    if result.detail_contract_error is not None:
        return "Card generation is blocked by sport adapter consistency checks."
    if result.generation_error_type is not None:
        return "Card generation failed before producing public cards."
    reasons = response.generation.validation_issues
    if reasons:
        return reasons[0]
    return {
        CardFeedStatus.no_pbp_yet: "No play-by-play source data is available for this game.",
        CardFeedStatus.unsupported_sport: "Narrative card generation does not support this sport.",
        CardFeedStatus.generation_pending: "Narrative card generation is pending.",
        CardFeedStatus.validation_blocked: "Narrative card generation is blocked.",
    }.get(response.generation.status)


def _cache_state(response: CardFeedResponse) -> str:
    if response.generation.is_stale:
        return "stale_regenerating"
    if response.cards:
        return "generated_on_request"
    return "empty"


def _source_hash_for_card_feed(
    game: SportsGame,
    league: str,
    sorted_plays: list[SportsGamePlay],
) -> str:
    last_play = sorted_plays[-1] if sorted_plays else None
    digest_input = {
        "gameId": game.id,
        "league": league,
        "status": game.status,
        "playCount": len(sorted_plays),
        "lastPlayIndex": last_play.play_index if last_play else None,
        "homeScore": getattr(last_play, "home_score", None),
        "awayScore": getattr(last_play, "away_score", None),
        "lastPbpAt": getattr(game, "last_pbp_at", None),
        "lastIngestedAt": getattr(game, "last_ingested_at", None),
        "plays": [
            {
                "playIndex": play.play_index,
                "period": play.quarter,
                "clock": play.game_clock,
                "type": play.play_type,
                "team": play.team.abbreviation if play.team else None,
                "player": play.player_name,
                "description": play.description,
                "homeScore": play.home_score,
                "awayScore": play.away_score,
                "raw": play.raw_data,
            }
            for play in sorted_plays
        ],
    }
    raw = json.dumps(digest_input, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


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
    spoiler_policy: SpoilerPolicy,
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
    description = _play_detail(play)
    content_depth = _content_depth(play)
    lead_in = _lead_in(play)
    stage_setting = _stage_setting(play, context)
    tags = _tags(play, content_depth)
    if play.mode_eligibility is None:
        raise DetailContractError("modeEligibility missing")
    if play.importance is None:
        raise DetailContractError("importance missing")
    impact = impact_for(play, score_change, impact_context)
    card = NarrativeCard(
        id=f"{game.id}:{play.play_index}",
        gameId=game.id,
        sourcePlayId=_source_play_id(play, football_context, source_play_id),
        playIndex=play.play_index,
        sport=sport,
        league=league,
        tier=tier,
        contentDepth=content_depth,
        modeEligibility=play.mode_eligibility,
        importance=play.importance,
        visualImportance=_visual_importance(play),
        period=CardPeriod(ordinal=play.quarter, label=play.period_label, type=play.period_type),
        displayTime=play.time_label or play.clock_label or play.period_label,
        clock=play.game_clock,
        team=_team_for_play(game, play.team_abbreviation),
        scoreBefore=score_before_for(play, context),
        scoreChange=score_change,
        scoreAfter=score_after_for(play, spoiler_policy, context),
        situation=_situation(
            play,
            mlb_context,
            nhl_context,
            basketball_context,
            football_context,
        ),
        leadIn=lead_in,
        stageSetting=stage_setting,
        headline=_headline(play),
        description=description,
        impact=impact,
        tags=tags,
        spoilerLevel=_spoiler_level(spoiler_policy, score_change),
        textFieldSpoilerLevels=_text_field_spoiler_levels(
            spoiler_policy,
            impact,
        ),
    )
    if spoiler_policy is SpoilerPolicy.pre_reveal:
        return _redact_pre_reveal_card(card)
    return card


def _response(
    *,
    game: SportsGame,
    sport: str,
    league: str,
    spoiler_policy: SpoilerPolicy,
    feed_status: CardFeedStatus,
    cards: list[NarrativeCard],
    last_play_index: int | None,
    sections: list[CardSectionLeadIn] | None = None,
    validation_issues: list[str] | None = None,
) -> CardFeedResponse:
    return CardFeedResponse(
        game=CardGameMetadata(
            gameId=game.id,
            sport=sport,
            league=league,
            status=game.status,
            homeTeam=game.home_team.name if game.home_team else None,
            awayTeam=game.away_team.name if game.away_team else None,
            homeTeamId=game.home_team.id if game.home_team else None,
            awayTeamId=game.away_team.id if game.away_team else None,
            homeTeamAbbr=game.home_team.abbreviation if game.home_team else None,
            awayTeamAbbr=game.away_team.abbreviation if game.away_team else None,
        ),
        spoilerPolicy=spoiler_policy,
        generation=FeedGenerationStatus(
            status=feed_status,
            cardCount=len(cards),
            lastPlayIndex=last_play_index,
            generatedAt=datetime.now(UTC) if cards else None,
            isStale=feed_status is CardFeedStatus.stale_regenerating,
            validationIssues=validation_issues or [],
        ),
        reveal=_reveal_availability(game, spoiler_policy),
        sections=sections or [],
        cards=cards,
    )


def _initial_status(
    game: SportsGame,
    league: str,
    sorted_plays: list[SportsGamePlay],
) -> CardFeedStatus:
    if league not in _SUPPORTED_SPORTS:
        return CardFeedStatus.unsupported_sport
    if not sorted_plays:
        return CardFeedStatus.no_pbp_yet
    if game.status == GameStatus.recap_pending.value:
        return CardFeedStatus.generation_pending
    if game.status == GameStatus.recap_failed.value:
        return CardFeedStatus.validation_blocked
    if game.status == GameStatus.live.value and _is_stale(game):
        return CardFeedStatus.stale_regenerating
    return CardFeedStatus.ready


def _state_issues(feed_status: CardFeedStatus) -> list[str]:
    if feed_status is CardFeedStatus.validation_blocked:
        return ["Card validation is blocked by upstream game state."]
    return []


def _is_stale(game: SportsGame) -> bool:
    last_pbp_at = getattr(game, "last_pbp_at", None)
    last_ingested_at = getattr(game, "last_ingested_at", None)
    return bool(last_pbp_at and last_ingested_at and last_pbp_at > last_ingested_at)


def _league_code(game: SportsGame) -> str:
    return (game.league.code if game.league else "UNKNOWN").upper()


def _plays_through(
    sorted_plays: list[SportsGamePlay],
    through_play_index: int | None,
) -> list[SportsGamePlay]:
    if through_play_index is None:
        return sorted_plays
    return [play for play in sorted_plays if play.play_index <= through_play_index]


def _reveal_availability(
    game: SportsGame,
    spoiler_policy: SpoilerPolicy,
) -> RevealAvailability:
    available = GameStatus.is_final_or_post_final_status(game.status)
    boundary_state: Literal["unavailable", "hidden_until_reveal", "allowed"]
    if not available:
        boundary_state = "unavailable"
    elif spoiler_policy is SpoilerPolicy.revealed:
        boundary_state = "allowed"
    else:
        boundary_state = "hidden_until_reveal"
    return RevealAvailability(
        available=available,
        status="ready" if available else "unavailable",
        scoresInCards=spoiler_policy is SpoilerPolicy.revealed,
        revealRequiredForScores=spoiler_policy is not SpoilerPolicy.revealed,
        completedGameBoundary=CompletedGameRevealBoundary(
            finalScore=boundary_state,
            winner=boundary_state,
            stats=boundary_state,
            payoffCopy=boundary_state,
        ),
    )


def _content_depth(play: PlayEntry) -> str:
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


def _team_for_play(game: SportsGame, abbreviation: str | None) -> CardTeam:
    home_abbr = game.home_team.abbreviation if game.home_team else None
    away_abbr = game.away_team.abbreviation if game.away_team else None
    if abbreviation and abbreviation == home_abbr:
        return CardTeam(abbreviation=abbreviation, name=game.home_team.name, side="home")
    if abbreviation and abbreviation == away_abbr:
        return CardTeam(abbreviation=abbreviation, name=game.away_team.name, side="away")
    return CardTeam(abbreviation=abbreviation, side="unknown")


def _situation(
    play: PlayEntry,
    mlb_context: MlbCardContext | None = None,
    nhl_context: NhlCardContext | None = None,
    basketball_context: BasketballCardContext | None = None,
    football_context: FootballCardContext | None = None,
) -> CardSituation:
    if mlb_context is not None:
        return CardSituation(summary=mlb_context.summary, raw=mlb_context.raw)
    if nhl_context is not None:
        return CardSituation(summary=nhl_context.summary, raw=nhl_context.raw)
    if basketball_context is not None:
        return CardSituation(summary=basketball_context.summary, raw=basketball_context.raw)
    if football_context is not None:
        return CardSituation(summary=football_context.summary, raw=football_context.raw)
    raw = play.situation_before or play.situation_after
    summary = None
    if isinstance(raw, dict):
        display = raw.get("display")
        if isinstance(display, dict):
            summary = display.get("headline")
    if not summary:
        summary = play.time_label or play.period_label
    return CardSituation(summary=summary, raw=raw)


def _source_play_id(
    play: PlayEntry,
    football_context: FootballCardContext | None = None,
    provider_source_id: str | None = None,
) -> str:
    if football_context and football_context.source_play_id:
        return football_context.source_play_id
    if provider_source_id:
        return provider_source_id
    return str(play.play_index)


def _provider_source_play_id(play: SportsGamePlay) -> str | None:
    if play.event_id is not None:
        return str(play.event_id)
    raw_data = play.raw_data if isinstance(play.raw_data, dict) else {}
    for key in ("sourceEventId", "source_event_id", "eventId", "event_id", "providerEventId"):
        value = raw_data.get(key)
        if isinstance(value, str | int) and not isinstance(value, bool):
            source_id = str(value).strip()
            if source_id:
                return source_id
    return None


def _lead_in(play: PlayEntry) -> str:
    parts = [
        (play.time_label or play.period_label or play.clock_label or "").strip(),
        (play.team_abbreviation or "").strip(),
    ]
    label = " - ".join(part for part in parts if part)
    return label or "Game event"


def _stage_setting(
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
        label = _nhl_stage_setting(context)
        if label:
            return label
    if isinstance(context, BasketballCardContext):
        label = _basketball_stage_setting(context)
        if label:
            return label
    if context and context.summary and not _contains_reveal_only_pressure(context.summary):
        return context.summary
    return _lead_in(play)


def _nhl_stage_setting(context: NhlCardContext) -> str | None:
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


def _basketball_stage_setting(context: BasketballCardContext) -> str | None:
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


def _headline(play: PlayEntry) -> str:
    if play.player_name and play.display_type:
        return f"{play.player_name} - {play.display_type}"
    return play.display_type or play.play_type or "Play"


def _tags(play: PlayEntry, content_depth: str) -> list[str]:
    tags: list[str] = []
    if play.display_type:
        tags.append(play.display_type)
    if play.importance:
        tags.extend(_tag_label(reason) for reason in play.importance.reasons)
    limit = {"extended": 5, "standard": 3, "brief": 2}[content_depth]
    return list(dict.fromkeys(tag for tag in tags if tag))[:limit]


def _play_detail(play: PlayEntry) -> str:
    description = _clean_text(play.description)
    if description and not _looks_like_raw_feed_text(description):
        return description
    return play.display_type or "Play"


def _clean_text(value: str | None) -> str:
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


def _redact_pre_reveal_card(card: NarrativeCard) -> NarrativeCard:
    impact = _downgrade_reveal_only_impact(card.impact, card.score_change)
    situation = card.situation.model_copy(
        update={
            "summary": _redact_situation_summary(card.situation.summary, card),
            "raw": _redact_raw_pressure(card.situation.raw),
        }
    )
    return card.model_copy(
        update={
            "impact": impact,
            "tags": _redact_tags(card.tags),
            "situation": situation,
            "text_field_spoiler_levels": _text_field_spoiler_levels(
                SpoilerPolicy.pre_reveal,
                impact,
            ),
        }
    )


def _redact_situation_summary(value: str | None, card: NarrativeCard) -> str | None:
    if not value or not _contains_reveal_only_pressure(value):
        return value
    return card.display_time or card.period.label or "Game event"


def _redact_tags(tags: list[str]) -> list[str]:
    return [
        tag
        for tag in tags
        if not any(part in tag.lower() for part in _REVEAL_ONLY_TAG_PARTS)
    ]


def _redact_raw_pressure(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_raw_pressure(item) for item in value]
    if not isinstance(value, dict):
        if isinstance(value, str) and _contains_reveal_only_pressure(value):
            return None
        return value

    redacted: dict[str, Any] = {}
    for key, item in deepcopy(value).items():
        normalized_key = key.lower()
        if normalized_key in _REVEAL_ONLY_RAW_KEYS:
            continue
        if normalized_key == "impact" and isinstance(item, str):
            redacted[key] = _downgrade_reveal_only_impact(item, None)
            continue
        nested = _redact_raw_pressure(item)
        if nested is not None and nested != {} and nested != []:
            redacted[key] = nested
    return redacted


def _contains_reveal_only_pressure(value: str) -> bool:
    lowered = value.lower()
    return bool(
        re.search(r"\b\d{1,2}\s*-\s*\d{1,2}\s+[a-z]{2,4}\s+run\b", lowered)
        or any(
            phrase in lowered
            for phrase in (
                "lead change",
                "tying",
                "go ahead",
                "go-ahead",
                "clutch",
                "late close",
                "empty net",
                "comeback",
                "blowout",
                "high scoring",
                "final score",
                "winner",
            )
        )
    )


def _downgrade_reveal_only_impact(
    impact: str | None,
    score_change: ScoreChange | None,
) -> str | None:
    if impact not in _REVEAL_ONLY_IMPACTS:
        return impact
    if score_change and (score_change.home or score_change.away):
        return "scoring"
    return None


def _text_field_spoiler_levels(
    spoiler_policy: SpoilerPolicy,
    impact: str | None,
) -> CardTextSpoilerLevels:
    impact_level = CardFieldSpoilerLevel.earned_at_play
    if spoiler_policy is SpoilerPolicy.revealed and impact in _REVEAL_ONLY_IMPACTS:
        impact_level = CardFieldSpoilerLevel.reveal_only
    return CardTextSpoilerLevels(
        leadIn=CardFieldSpoilerLevel.earned_at_play,
        stageSetting=CardFieldSpoilerLevel.earned_at_play,
        headline=CardFieldSpoilerLevel.earned_at_play,
        description=CardFieldSpoilerLevel.earned_at_play,
        impact=impact_level if impact else None,
        situationSummary=CardFieldSpoilerLevel.earned_at_play,
        tags=CardFieldSpoilerLevel.earned_at_play,
    )


def _visual_importance(play: PlayEntry) -> str:
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


def _spoiler_level(spoiler_policy: SpoilerPolicy, score_change: ScoreChange) -> str:
    if spoiler_policy is SpoilerPolicy.revealed:
        return "score_revealed"
    if score_change.home or score_change.away:
        return "score_change"
    return "none"
