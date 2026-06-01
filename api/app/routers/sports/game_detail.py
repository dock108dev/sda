"""Game detail and preview-score endpoints."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...db import AsyncSession, get_db
from ...db.flow import SportsGameFlow
from ...db.mlb_advanced import (
    MLBGameAdvancedStats,
    MLBPitcherGameStats,
    MLBPlayerAdvancedStats,
    MLBPlayerFieldingStats,
)
from ...db.nba_advanced import (
    NBAGameAdvancedStats,
    NBAPlayerAdvancedStats,
)
from ...db.ncaab_advanced import (
    NCAABGameAdvancedStats,
    NCAABPlayerAdvancedStats,
)
from ...db.nfl_advanced import (
    NFLGameAdvancedStats,
    NFLPlayerAdvancedStats,
)
from ...db.nhl_advanced import (
    NHLGameAdvancedStats,
    NHLGoalieAdvancedStats,
    NHLSkaterAdvancedStats,
)
from ...db.social import TeamSocialPost
from ...db.sports import (
    GameStatus,
    SportsGame,
    SportsGamePlay,
    SportsPlayerBoxscore,
    SportsTeamBoxscore,
)
from ...feed.debug_schemas import CardGenerationDebugResponse
from ...game_metadata.nuggets import generate_nugget
from ...game_metadata.scoring import excitement_score, quality_score
from ...game_metadata.services import RatingsService, StandingsService
from ...scroll_down_mlb import service as scroll_down_mlb_service
from ...scroll_down_mlb.data_source import load_game_payload as load_scroll_down_mlb_payload
from ...scroll_down_mlb.schemas import (
    GenerationPolicy,
    ScrollDownMlbDeckResponse,
    ValidationWarning,
)
from ...services.derived_metrics import compute_derived_metrics
from ...services.game_status import compute_status_flags
from ...services.odds_table import build_odds_table
from ...services.period_labels import period_label, time_label
from ...services.play_importance import (
    DetailContractError,
    enrich_play_importance,
    validate_detail_contract,
)
from ...services.play_tiers import classify_all_tiers, enrich_play_entries, group_tier3_plays
from ...services.stat_annotations import compute_team_annotations
from ...services.team_colors import get_matchup_colors
from .common import (
    serialize_mlb_batter,
    serialize_mlb_pitcher,
    serialize_nhl_goalie,
    serialize_nhl_skater,
    serialize_play_entry,
    serialize_player_stat,
    serialize_team_stat,
)
from .game_detail_advanced import (
    serialize_mlb_advanced,
    serialize_nba_advanced,
    serialize_ncaab_advanced,
    serialize_nfl_advanced,
    serialize_nhl_advanced,
)
from .game_helpers import (
    build_preview_context,
    normalize_score,
    preview_tags,
    resolve_team_key,
    select_preview_entry,
    serialize_social_posts,
)
from .nhl_helpers import compute_nhl_data_health
from .schemas import (
    GameDetailResponse,
    GameMeta,
    GamePreviewScoreResponse,
    LiveSnapshot,
    MLBBatterStat,
    MLBPitcherStat,
    NHLGoalieStat,
    NHLSkaterStat,
    OddsEntry,
    ScrollDownMlbAdminDebugFinding,
    ScrollDownMlbAdminDebugResponse,
    ScrollDownMlbAdminHalfInningDebug,
)
from .schemas.common import _score_obj

router = APIRouter()
logger = logging.getLogger(__name__)


def _scroll_down_debug_finding(
    *,
    code: str,
    severity: str,
    message: str,
    play_id: str | None = None,
    scope: str | None = None,
) -> ScrollDownMlbAdminDebugFinding:
    return ScrollDownMlbAdminDebugFinding(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        message=message,
        play_id=play_id,
        scope=scope,
    )


def _builder_finding_to_admin(
    finding: ValidationWarning,
) -> ScrollDownMlbAdminDebugFinding:
    return _scroll_down_debug_finding(
        code=finding.code,
        severity=finding.severity.value,
        message=finding.message,
        play_id=finding.play_id,
        scope="deck",
    )


def _status_for_findings(
    findings: list[ScrollDownMlbAdminDebugFinding],
) -> str:
    if any(f.severity == "error" for f in findings):
        return "error"
    if findings:
        return "warning"
    return "ok"


def _half_inning_debug(
    deck: ScrollDownMlbDeckResponse,
) -> tuple[
    list[ScrollDownMlbAdminHalfInningDebug],
    list[ScrollDownMlbAdminDebugFinding],
]:
    """Validate half-inning containers and return admin summaries/findings."""
    play_index_counts: dict[int, int] = {}
    for container in deck.half_innings:
        for event in container.events:
            play_index_counts[event.play_index] = (
                play_index_counts.get(event.play_index, 0) + 1
            )

    rows: list[ScrollDownMlbAdminHalfInningDebug] = []
    all_findings: list[ScrollDownMlbAdminDebugFinding] = []
    max_play_index: int | None = None

    for container in deck.half_innings:
        scope = f"{container.inning}:{container.half}"
        event_indices = [event.play_index for event in container.events]
        event_index_set = set(event_indices)
        selected_index_set = set(container.selected_play_indices)
        findings: list[ScrollDownMlbAdminDebugFinding] = []

        if not container.events:
            findings.append(
                _scroll_down_debug_finding(
                    code="empty_half_inning",
                    severity="warning",
                    message="Half-inning container has no events.",
                    scope=scope,
                )
            )

        for play_index in sorted(event_index_set):
            if play_index_counts.get(play_index, 0) > 1:
                findings.append(
                    _scroll_down_debug_finding(
                        code="duplicate_event_play_index",
                        severity="error",
                        message=f"playIndex {play_index} appears in multiple half-inning events.",
                        play_id=str(play_index),
                        scope=scope,
                    )
                )

        for play_index in sorted(selected_index_set - event_index_set):
            findings.append(
                _scroll_down_debug_finding(
                    code="selected_play_index_missing_event",
                    severity="error",
                    message=f"selectedPlayIndices contains {play_index}, but no event in this half has that playIndex.",
                    play_id=str(play_index),
                    scope=scope,
                )
            )

        for event in container.events:
            max_play_index = (
                event.play_index
                if max_play_index is None
                else max(max_play_index, event.play_index)
            )
            selected_by_list = event.play_index in selected_index_set
            if event.is_selected != selected_by_list:
                findings.append(
                    _scroll_down_debug_finding(
                        code="event_selected_flag_mismatch",
                        severity="error",
                        message=(
                            f"event.isSelected={event.is_selected} disagrees with "
                            f"selectedPlayIndices membership for playIndex {event.play_index}."
                        ),
                        play_id=str(event.play_index),
                        scope=scope,
                    )
                )
            if not event.result.label.strip():
                findings.append(
                    _scroll_down_debug_finding(
                        code="event_result_label_empty",
                        severity="warning",
                        message=f"Event {event.play_index} has an empty result label.",
                        play_id=str(event.play_index),
                        scope=scope,
                    )
                )

        all_findings.extend(findings)
        rows.append(
            ScrollDownMlbAdminHalfInningDebug(
                inning=container.inning,
                half=container.half,
                batting_team=container.batting_team.abbreviation,
                fielding_team=container.fielding_team.abbreviation,
                event_count=len(container.events),
                selected_count=len(container.selected_play_indices),
                scored_runs=container.meta.scored_runs,
                had_activity=container.meta.had_activity,
                had_lead_change=container.meta.had_lead_change,
                had_tying=container.meta.had_tying,
                min_play_index=min(event_indices) if event_indices else None,
                max_play_index=max(event_indices) if event_indices else None,
                status=_status_for_findings(findings),  # type: ignore[arg-type]
                findings=findings,
            )
        )

    if max_play_index is not None and deck.last_play_index != max_play_index:
        all_findings.append(
            _scroll_down_debug_finding(
                code="deck_last_play_index_mismatch",
                severity="warning",
                message=(
                    f"deck.lastPlayIndex is {deck.last_play_index}, but max "
                    f"half-inning event playIndex is {max_play_index}."
                ),
                play_id=str(max_play_index),
                scope="deck",
            )
        )

    return rows, all_findings


def _scroll_down_debug_response_from_deck(
    *,
    deck: ScrollDownMlbDeckResponse,
    builder_warnings: list[ValidationWarning] | None = None,
    builder_errors: list[ValidationWarning] | None = None,
) -> ScrollDownMlbAdminDebugResponse:
    half_innings, half_findings = _half_inning_debug(deck)
    warnings = [
        _builder_finding_to_admin(w) for w in (builder_warnings or deck.validation_warnings)
    ]
    errors = [_builder_finding_to_admin(e) for e in (builder_errors or [])]
    warnings.extend(f for f in half_findings if f.severity != "error")
    errors.extend(f for f in half_findings if f.severity == "error")
    event_count = sum(row.event_count for row in half_innings)
    selected_event_count = sum(row.selected_count for row in half_innings)
    return ScrollDownMlbAdminDebugResponse(
        available=True,
        status="available",
        reason=None,
        policy="official" if deck.is_final else "live",
        deck_version=deck.deck_version,
        is_final=deck.is_final,
        card_count=len(deck.cards),
        last_play_index=deck.last_play_index,
        half_inning_count=len(half_innings),
        event_count=event_count,
        selected_event_count=selected_event_count,
        warnings=warnings,
        errors=errors,
        half_innings=half_innings,
        deck=deck.model_dump(mode="json", by_alias=True),
    )


@router.get("/games/{game_id}/preview-score", response_model=GamePreviewScoreResponse)
async def get_game_preview_score(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> GamePreviewScoreResponse:
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game Data Not Found",
        )
    if not game.home_team or not game.away_team:
        logger.error("Preview score missing team data", extra={"game_id": game_id})
        raise HTTPException(
            status_code=422,
            detail="Game missing team data",
        )

    league_code = game.league.code if game.league else "UNKNOWN"
    ratings_service = RatingsService()
    standings_service = StandingsService()

    try:
        ratings = ratings_service.get_ratings(league_code)
        standings = standings_service.get_standings(league_code)
        home_key = resolve_team_key(game.home_team)
        away_key = resolve_team_key(game.away_team)
        home_rating = select_preview_entry(ratings, home_key, "ratings")
        away_rating = select_preview_entry(ratings, away_key, "ratings")
        home_standing = select_preview_entry(standings, home_key, "standings")
        away_standing = select_preview_entry(standings, away_key, "standings")
    except Exception as exc:
        logger.exception("Failed to build preview score", extra={"game_id": game_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Preview score unavailable",
        ) from exc

    context = build_preview_context(game, home_rating, away_rating)
    tags = preview_tags(home_rating, away_rating, home_standing, away_standing)
    preview = GamePreviewScoreResponse(
        game_id=str(game.id),
        excitement_score=normalize_score(excitement_score(context)),
        quality_score=normalize_score(
            quality_score(home_rating, away_rating, home_standing, away_standing)
        ),
        tags=tags,
        nugget=generate_nugget(context, tags),
    )
    return preview


@router.get(
    "/games/{game_id}/card-generation-debug",
    response_model=CardGenerationDebugResponse,
    response_model_by_alias=True,
)
async def get_game_card_generation_debug(
    game_id: int,
    spoiler_policy: Literal["pre_reveal", "revealed"] = Query(
        "pre_reveal",
        alias="spoilerPolicy",
    ),
    through_play_index: int | None = Query(None, ge=0, alias="throughPlayIndex"),
    include_feed: bool = Query(True, alias="includeFeed"),
    session: AsyncSession = Depends(get_db),
) -> CardGenerationDebugResponse:
    """Admin-only view of cross-sport narrative card generation state."""
    from ...feed.schemas import SpoilerPolicy
    from ...feed.service import build_card_generation_debug_from_game

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game Data Not Found",
        )
    return build_card_generation_debug_from_game(
        game,
        SpoilerPolicy(spoiler_policy),
        through_play_index=through_play_index,
        include_feed=include_feed,
    )


@router.get(
    "/games/{game_id}/scroll-down-mlb-debug",
    response_model=ScrollDownMlbAdminDebugResponse,
    response_model_by_alias=True,
)
async def get_game_scroll_down_mlb_debug(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> ScrollDownMlbAdminDebugResponse:
    """Admin-only view of the current Scroll Down MLB deck/debug state."""
    result = await session.execute(
        select(SportsGame)
        .options(selectinload(SportsGame.league))
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game Data Not Found",
        )

    league_code = game.league.code if game.league else None
    if (league_code or "").lower() != "mlb":
        return ScrollDownMlbAdminDebugResponse(
            available=False,
            status="not_available",
            reason="Scroll Down MLB debug is only available for MLB games.",
        )

    if (game.status or "").lower() in ("scheduled", "pregame"):
        return ScrollDownMlbAdminDebugResponse(
            available=False,
            status="not_available",
            reason="Scroll Down MLB deck is not available before first pitch.",
            policy="live",
        )

    deck = await scroll_down_mlb_service.get_game_deck(session, str(game_id))
    if deck is not None:
        return _scroll_down_debug_response_from_deck(deck=deck)

    payload = await load_scroll_down_mlb_payload(session, game_id)
    if payload is None:
        return ScrollDownMlbAdminDebugResponse(
            available=False,
            status="not_available",
            reason="No Scroll Down MLB source payload is available for this game.",
        )

    policy = (
        GenerationPolicy.official
        if GameStatus.is_final_or_post_final_status(game.status)
        else GenerationPolicy.live
    )
    outcome = scroll_down_mlb_service.build_deck_from_upstream(
        payload,
        policy=policy,
    )
    if outcome.deck is not None:
        return _scroll_down_debug_response_from_deck(
            deck=outcome.deck,
            builder_warnings=outcome.warnings,
            builder_errors=outcome.errors,
        )

    return ScrollDownMlbAdminDebugResponse(
        available=False,
        status="blocked" if outcome.blocked else "not_available",
        reason=(
            "Scroll Down MLB deck generation is blocked by validation errors."
            if outcome.blocked
            else "Scroll Down MLB deck generation did not produce a deck."
        ),
        policy=policy.value,
        warnings=[_builder_finding_to_admin(w) for w in outcome.warnings],
        errors=[_builder_finding_to_admin(e) for e in outcome.errors],
    )


@router.post("/games/{game_id}/scroll-down-mlb-precompute")
async def precompute_scroll_down_mlb_deck(
    game_id: int,
    force: bool = False,
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Admin trigger for persisted Scroll Down MLB deck generation."""
    result = await scroll_down_mlb_service.precompute_game_deck(
        session,
        game_id,
        force=force,
    )
    return {
        "gameId": str(result.game_id),
        "status": result.status,
        "deckVersion": result.deck_version,
        "sourceHash": result.source_hash,
        "error": result.error,
    }


@router.get("/games/{game_id}/admin-detail", response_model=GameDetailResponse)
async def get_game(game_id: int, session: AsyncSession = Depends(get_db)) -> GameDetailResponse:
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.team_boxscores).selectinload(SportsTeamBoxscore.team),
            selectinload(SportsGame.player_boxscores).selectinload(SportsPlayerBoxscore.team),
            selectinload(SportsGame.odds),
            selectinload(SportsGame.social_posts).selectinload(TeamSocialPost.team),
            selectinload(SportsGame.plays).selectinload(SportsGamePlay.team),
            selectinload(SportsGame.timeline_artifacts),
            selectinload(SportsGame.advanced_stats).selectinload(MLBGameAdvancedStats.team),
            selectinload(SportsGame.player_advanced_stats).selectinload(
                MLBPlayerAdvancedStats.team
            ),
            selectinload(SportsGame.pitcher_game_stats).selectinload(
                MLBPitcherGameStats.team
            ),
            selectinload(SportsGame.fielding_stats).selectinload(
                MLBPlayerFieldingStats.team
            ),
            selectinload(SportsGame.nba_advanced_stats).selectinload(
                NBAGameAdvancedStats.team
            ),
            selectinload(SportsGame.nba_player_advanced_stats).selectinload(
                NBAPlayerAdvancedStats.team
            ),
            selectinload(SportsGame.nhl_advanced_stats).selectinload(
                NHLGameAdvancedStats.team
            ),
            selectinload(SportsGame.nhl_skater_advanced_stats).selectinload(
                NHLSkaterAdvancedStats.team
            ),
            selectinload(SportsGame.nhl_goalie_advanced_stats).selectinload(
                NHLGoalieAdvancedStats.team
            ),
            selectinload(SportsGame.nfl_advanced_stats).selectinload(
                NFLGameAdvancedStats.team
            ),
            selectinload(SportsGame.nfl_player_advanced_stats).selectinload(
                NFLPlayerAdvancedStats.team
            ),
            selectinload(SportsGame.ncaab_advanced_stats).selectinload(
                NCAABGameAdvancedStats.team
            ),
            selectinload(SportsGame.ncaab_player_advanced_stats).selectinload(
                NCAABPlayerAdvancedStats.team
            ),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")

    # Determine league
    league_code = game.league.code if game.league else None
    is_nhl = league_code == "NHL"
    is_mlb = league_code == "MLB"

    team_stats = [serialize_team_stat(box, league_code=league_code) for box in game.team_boxscores]

    # For NHL/MLB, separate into sport-specific lists; for other sports use generic player stats
    nhl_skaters: list[NHLSkaterStat] | None = None
    nhl_goalies: list[NHLGoalieStat] | None = None
    mlb_batters: list[MLBBatterStat] | None = None
    mlb_pitchers: list[MLBPitcherStat] | None = None
    player_stats: list = []

    if is_nhl:
        # NHL: populate sport-specific lists sorted by TOI desc, leave player_stats empty
        skaters = []
        goalies = []
        for player in game.player_boxscores:
            stats = player.stats or {}
            player_role = stats.get("player_role")
            if player_role == "goalie":
                goalies.append(serialize_nhl_goalie(player))
            else:
                skaters.append(serialize_nhl_skater(player))

        def _toi_sort_key(p) -> float:
            """Extract TOI as minutes for sorting (higher = first)."""
            toi = getattr(p, "toi", None)
            if isinstance(toi, str) and ":" in toi:
                parts = toi.split(":")
                return int(parts[0]) + int(parts[1]) / 60
            return 0.0

        nhl_skaters = sorted(skaters, key=_toi_sort_key, reverse=True)
        nhl_goalies = sorted(goalies, key=_toi_sort_key, reverse=True)
    elif is_mlb:
        # MLB: separate batters and pitchers, leave player_stats empty
        batters = []
        pitchers = []
        for player in game.player_boxscores:
            stats = player.stats or {}
            player_role = stats.get("player_role")
            if player_role == "pitcher":
                pitchers.append(serialize_mlb_pitcher(player))
            else:
                batters.append(serialize_mlb_batter(player))
        mlb_batters = batters
        mlb_pitchers = pitchers
    else:
        # Non-NHL/MLB: use generic player stats
        player_stats = [
            serialize_player_stat(player, league_code=league_code)
            for player in game.player_boxscores
        ]

    odds_entries = [
        OddsEntry(
            book=odd.book,
            market_type=odd.market_type,
            market_category=odd.market_category,
            player_name=odd.player_name,
            description=odd.description,
            side=odd.side,
            line=odd.line,
            price=odd.price,
            is_closing_line=odd.is_closing_line,
            observed_at=odd.observed_at,
        )
        for odd in game.odds
    ]

    plays_entries = [
        serialize_play_entry(play, league_code)
        for play in sorted(game.plays, key=lambda p: p.play_index)
    ]
    if not plays_entries:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game Detail Not Found",
        )

    home_abbr_val = game.home_team.abbreviation if game.home_team else None
    away_abbr_val = game.away_team.abbreviation if game.away_team else None

    # Classify play tiers and build grouped plays
    if league_code:
        tiers = classify_all_tiers(plays_entries, league_code)
        for entry, t in zip(plays_entries, tiers, strict=False):
            entry.tier = t
        grouped_plays = group_tier3_plays(plays_entries, tiers)
        if home_abbr_val and away_abbr_val:
            try:
                enrich_play_entries(plays_entries, league_code, home_abbr_val, away_abbr_val)
                enrich_play_importance(
                    plays_entries,
                    league_code=league_code,
                    home_abbr=home_abbr_val,
                    away_abbr=away_abbr_val,
                )
                validate_detail_contract(plays_entries)
            except DetailContractError as exc:
                logger.warning("Incomplete game detail contract for game %s: %s", game_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Game Detail Incomplete",
                ) from exc
            except Exception as exc:
                logger.exception("Detail enrichment failed for game %s", game_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Detail Enrichment Failed",
                ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Game Detail Incomplete",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Game Detail Incomplete",
        )

    # Check if game has a flow in SportsGameFlow table
    flow_check = await session.execute(
        select(SportsGameFlow.id)
        .where(
            SportsGameFlow.game_id == game_id,
            SportsGameFlow.moments_json.isnot(None),
        )
        .limit(1)
    )
    has_flow = flow_check.scalar() is not None

    matchup_colors = get_matchup_colors(
        game.home_team.color_light_hex if game.home_team else None,
        game.home_team.color_dark_hex if game.home_team else None,
        game.away_team.color_light_hex if game.away_team else None,
        game.away_team.color_dark_hex if game.away_team else None,
        away_secondary_light=game.away_team.color_secondary_light_hex if game.away_team else None,
        away_secondary_dark=game.away_team.color_secondary_dark_hex if game.away_team else None,
    )

    status_flags = compute_status_flags(game.status)
    latest_play = max(game.plays, key=lambda p: p.play_index, default=None) if game.plays else None
    meta_current_period = getattr(latest_play, "quarter", None) if latest_play else None
    meta_game_clock = getattr(latest_play, "game_clock", None) if latest_play else None

    meta_period_label: str | None = None
    meta_live_snapshot: LiveSnapshot | None = None
    if meta_current_period is not None and league_code:
        meta_period_label = period_label(meta_current_period, league_code)
        meta_live_snapshot = LiveSnapshot(
            period_label=meta_period_label,
            time_label=time_label(meta_current_period, meta_game_clock, league_code),
            score=_score_obj(game.home_score, game.away_score),
            current_period=meta_current_period,
            game_clock=meta_game_clock,
        )

    meta = GameMeta(
        id=game.id,
        league_code=game.league.code if game.league else "UNKNOWN",
        season=game.season,
        season_type=getattr(game, "season_type", None),
        game_date=game.game_date,
        local_game_date=getattr(game, "local_game_date", None),
        home_team=game.home_team.name if game.home_team else "Unknown",
        away_team=game.away_team.name if game.away_team else "Unknown",
        home_team_id=game.home_team.id if game.home_team else None,
        away_team_id=game.away_team.id if game.away_team else None,
        score=_score_obj(game.home_score, game.away_score),
        status=game.status,
        scrape_version=getattr(game, "scrape_version", None),
        last_scraped_at=game.last_scraped_at,
        last_ingested_at=game.last_ingested_at,
        last_pbp_at=game.last_pbp_at,
        last_social_at=game.last_social_at,
        last_odds_at=game.last_odds_at,
        last_advanced_stats_at=getattr(game, "last_advanced_stats_at", None),
        has_boxscore=bool(game.team_boxscores),
        has_player_stats=bool(game.player_boxscores),
        has_odds=bool(game.odds),
        has_social=bool(game.social_posts),
        has_pbp=bool(game.plays),
        has_flow=has_flow,
        has_advanced_stats=getattr(game, "last_advanced_stats_at", None) is not None,
        play_count=len(game.plays) if game.plays else 0,
        social_post_count=len(game.social_posts) if game.social_posts else 0,
        home_team_x_handle=game.home_team.x_handle if game.home_team else None,
        away_team_x_handle=game.away_team.x_handle if game.away_team else None,
        homeTeamAbbr=game.home_team.abbreviation if game.home_team else None,
        awayTeamAbbr=game.away_team.abbreviation if game.away_team else None,
        homeTeamColorLight=matchup_colors["homeLightHex"],
        homeTeamColorDark=matchup_colors["homeDarkHex"],
        awayTeamColorLight=matchup_colors["awayLightHex"],
        awayTeamColorDark=matchup_colors["awayDarkHex"],
        is_truly_completed=status_flags["is_truly_completed"],
        read_eligible=status_flags["read_eligible"],
        current_period_label=meta_period_label,
        live_snapshot=meta_live_snapshot,
    )

    social_posts_entries = serialize_social_posts(game, game.social_posts or [])

    derived = compute_derived_metrics(game, game.odds)
    raw_payloads = {
        "team_boxscores": [
            {
                "team": box.team.name if box.team else "Unknown",
                "stats": box.stats,
                "source": box.source,
            }
            for box in game.team_boxscores
            if box.stats
        ],
        "player_boxscores": [
            {
                "team": player.team.name if player.team else "Unknown",
                "player": player.player_name,
                "stats": player.stats,
            }
            for player in game.player_boxscores
            if player.stats
        ],
        "odds": [
            {
                "book": odd.book,
                "market_type": odd.market_type,
                "raw": odd.raw_payload,
            }
            for odd in game.odds
            if odd.raw_payload
        ],
    }

    # Compute NHL-specific data health (None for non-NHL games)
    data_health = compute_nhl_data_health(game, game.player_boxscores)

    odds_table = build_odds_table(game.odds) if game.odds else None

    stat_annotations: list[dict] | None = None
    home_box = next((b for b in game.team_boxscores if b.is_home), None)
    away_box = next((b for b in game.team_boxscores if not b.is_home), None)
    if home_box and away_box and league_code:
        home_abbr = game.home_team.abbreviation if game.home_team else None
        away_abbr = game.away_team.abbreviation if game.away_team else None
        if home_abbr and away_abbr:
            stat_annotations = compute_team_annotations(
                home_box.stats or {},
                away_box.stats or {},
                home_abbr,
                away_abbr,
                league_code,
            )

    # Advanced stats serialization (delegated to game_detail_advanced module)
    is_nba = league_code == "NBA"
    is_nfl = league_code == "NFL"
    is_ncaab = league_code == "NCAAB"

    mlb_advanced_stats_list, mlb_advanced_player_stats_list, mlb_pitcher_game_stats_list, mlb_fielding_stats_list = serialize_mlb_advanced(game) if is_mlb else (None, None, None, None)
    nba_advanced_stats_list, nba_player_advanced_stats_list = serialize_nba_advanced(game) if is_nba else (None, None)
    nhl_advanced_stats_list, nhl_skater_advanced_stats_list, nhl_goalie_advanced_stats_list = serialize_nhl_advanced(game) if is_nhl else (None, None, None)
    nfl_advanced_stats_list, nfl_player_advanced_stats_list = serialize_nfl_advanced(game) if is_nfl else (None, None)
    ncaab_advanced_stats_list, ncaab_player_advanced_stats_list = serialize_ncaab_advanced(game) if is_ncaab else (None, None)

    return GameDetailResponse(
        game=meta,
        team_stats=team_stats,
        player_stats=player_stats,
        nhl_skaters=nhl_skaters,
        nhl_goalies=nhl_goalies,
        mlb_batters=mlb_batters,
        mlb_pitchers=mlb_pitchers,
        mlb_advanced_stats=mlb_advanced_stats_list,
        mlb_advanced_player_stats=mlb_advanced_player_stats_list,
        mlb_pitcher_game_stats=mlb_pitcher_game_stats_list,
        mlb_fielding_stats=mlb_fielding_stats_list,
        nba_advanced_stats=nba_advanced_stats_list,
        nba_player_advanced_stats=nba_player_advanced_stats_list,
        nhl_advanced_stats=nhl_advanced_stats_list,
        nhl_skater_advanced_stats=nhl_skater_advanced_stats_list,
        nhl_goalie_advanced_stats=nhl_goalie_advanced_stats_list,
        nfl_advanced_stats=nfl_advanced_stats_list,
        nfl_player_advanced_stats=nfl_player_advanced_stats_list,
        ncaab_advanced_stats=ncaab_advanced_stats_list,
        ncaab_player_advanced_stats=ncaab_player_advanced_stats_list,
        odds=odds_entries,
        social_posts=social_posts_entries,
        plays=plays_entries,
        grouped_plays=grouped_plays,
        derived_metrics=derived,
        raw_payloads=raw_payloads,
        data_health=data_health,
        odds_table=odds_table,
        stat_annotations=stat_annotations,
    )
