"""Minimal Scroll Down Sports catch-up endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, desc, exists, func, or_, select
from sqlalchemy.orm import selectinload

from ...db import AsyncSession, get_db
from ...db.sports import (
    GameStatus,
    SportsGame,
    SportsGamePlay,
    SportsLeague,
    SportsPlayerBoxscore,
    SportsTeam,
    SportsTeamBoxscore,
)
from ...services.catchup_context import (
    build_catchup_context,
    enhance_catchup_context_with_openai,
)
from ...services.period_labels import period_label, time_label
from ...services.play_importance import (
    DetailContractError,
    enrich_play_importance,
    validate_detail_contract,
)
from ...services.play_tiers import classify_all_tiers, enrich_play_entries
from ...utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc, today_et
from .common import (
    serialize_mlb_batter,
    serialize_mlb_pitcher,
    serialize_nhl_goalie,
    serialize_nhl_skater,
    serialize_play_entry,
    serialize_player_stat,
    serialize_team_stat,
)
from .schemas.catchup import (
    CatchupGameContextResponse,
    CatchupGameDetailResponse,
    CatchupGameListResponse,
    CatchupGameMeta,
    CatchupGameSummary,
)
from .schemas.common import LiveSnapshot, PlayEntry, _score_obj

router = APIRouter()
logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_HOURS = 72
_DEFAULT_LOOKAHEAD_HOURS = 48
_PLAYS_PER_READING_MINUTE = 12
GameListSort = Literal["chronological", "currentSlate"]


def _game_window(
    start_date: date | None,
    end_date: date | None,
) -> tuple[datetime, datetime]:
    if start_date or end_date:
        start = start_of_et_day_utc(start_date) if start_date else datetime.min.replace(tzinfo=UTC)
        end = end_of_et_day_utc(end_date) if end_date else datetime.max.replace(tzinfo=UTC)
        return start, end

    now = datetime.now(UTC)
    return (
        now - timedelta(hours=_DEFAULT_LOOKBACK_HOURS),
        now + timedelta(hours=_DEFAULT_LOOKAHEAD_HOURS),
    )


def _team_filter(pattern: str):
    return or_(
        SportsGame.home_team.has(SportsTeam.name.ilike(pattern)),
        SportsGame.away_team.has(SportsTeam.name.ilike(pattern)),
        SportsGame.home_team.has(SportsTeam.short_name.ilike(pattern)),
        SportsGame.away_team.has(SportsTeam.short_name.ilike(pattern)),
        SportsGame.home_team.has(SportsTeam.abbreviation.ilike(pattern)),
        SportsGame.away_team.has(SportsTeam.abbreviation.ilike(pattern)),
    )


def _latest_snapshot(
    game: SportsGame,
    latest_period: int | None,
    latest_clock: str | None,
) -> tuple[str | None, LiveSnapshot | None]:
    league_code = game.league.code if game.league else None
    if latest_period is None or not league_code:
        return None, None

    label = period_label(latest_period, league_code)
    return (
        label,
        LiveSnapshot(
            period_label=label,
            time_label=time_label(latest_period, latest_clock, league_code),
            current_period=latest_period,
            game_clock=latest_clock,
        ),
    )


def _estimated_reading_minutes(play_count: int) -> int | None:
    if play_count <= 0:
        return None
    return max(1, (play_count + _PLAYS_PER_READING_MINUTE - 1) // _PLAYS_PER_READING_MINUTE)


def _summary(
    game: SportsGame,
    *,
    has_boxscore: bool,
    has_player_stats: bool,
    play_count: int,
    latest_period: int | None = None,
    latest_clock: str | None = None,
) -> CatchupGameSummary:
    period_label_value, live_snapshot = _latest_snapshot(game, latest_period, latest_clock)
    context = build_catchup_context(
        game,
        players=[],
        team_stats=[],
        plays=[],
    )
    return CatchupGameSummary(
        id=game.id,
        league_code=game.league.code if game.league else "UNKNOWN",
        game_date=game.game_date,
        local_game_date=getattr(game, "local_game_date", None),
        home_team=game.home_team.name if game.home_team else "Unknown",
        away_team=game.away_team.name if game.away_team else "Unknown",
        home_team_id=game.home_team.id if game.home_team else None,
        away_team_id=game.away_team.id if game.away_team else None,
        home_team_abbr=game.home_team.abbreviation if game.home_team else None,
        away_team_abbr=game.away_team.abbreviation if game.away_team else None,
        status=game.status,
        current_period=latest_period,
        game_clock=latest_clock,
        current_period_label=period_label_value,
        live_snapshot=live_snapshot,
        has_boxscore=has_boxscore,
        has_player_stats=has_player_stats,
        has_pbp=play_count > 0,
        play_count=play_count,
        estimated_reading_minutes=_estimated_reading_minutes(play_count),
        context=context,
    )


def _ordered_games_stmt(stmt, sort: GameListSort):
    """Apply feed ordering before pagination."""
    if sort == "chronological":
        return stmt.order_by(SportsGame.game_date.asc(), SportsGame.id.asc())

    now = datetime.now(UTC)
    today = today_et()

    slate_rank = case(
        (SportsGame.status == GameStatus.live.value, 0),
        (
            SportsGame.status.in_((GameStatus.scheduled.value, GameStatus.pregame.value))
            & (SportsGame.local_game_date == today),
            1,
        ),
        (
            SportsGame.status.in_((GameStatus.scheduled.value, GameStatus.pregame.value))
            & (SportsGame.game_date >= now),
            2,
        ),
        (SportsGame.status.in_(GameStatus.final_or_post_final_values()), 3),
        else_=4,
    )
    ascending_time = case(
        (slate_rank.in_((0, 1, 2)), SportsGame.game_date),
        else_=None,
    )
    descending_time = case(
        (slate_rank.in_((3, 4)), SportsGame.game_date),
        else_=None,
    )
    return stmt.order_by(
        slate_rank.asc(),
        ascending_time.asc().nullslast(),
        descending_time.desc().nullslast(),
        SportsGame.id.asc(),
    )


def _enrich_detail_plays(
    *,
    game_id: int,
    plays: list[PlayEntry],
    league_code: str | None,
    home_abbr: str | None,
    away_abbr: str | None,
) -> None:
    if not plays:
        return
    if not league_code or not home_abbr or not away_abbr:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Game Detail Incomplete",
        )

    try:
        tiers = classify_all_tiers(plays, league_code)
        for entry, tier in zip(plays, tiers, strict=False):
            entry.tier = tier
        enrich_play_entries(plays, league_code, home_abbr, away_abbr)
        enrich_play_importance(
            plays,
            league_code=league_code,
            home_abbr=home_abbr,
            away_abbr=away_abbr,
        )
        validate_detail_contract(plays)
    except DetailContractError as exc:
        logger.warning("Incomplete catch-up detail contract for game %s: %s", game_id, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Game Detail Incomplete",
        ) from exc
    except Exception as exc:
        logger.exception("Catch-up detail enrichment failed for game %s", game_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Detail Enrichment Failed",
        ) from exc


@router.get(
    "/games",
    response_model=CatchupGameListResponse,
    response_model_exclude_none=True,
)
async def list_catchup_games(
    session: AsyncSession = Depends(get_db),
    league: list[str] | None = Query(None),
    team: str | None = Query(None),
    startDate: date | None = Query(None, alias="startDate"),
    endDate: date | None = Query(None, alias="endDate"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: GameListSort = Query("chronological"),
) -> CatchupGameListResponse:
    """Return the catch-up list: games from -72h to +48h by default."""
    window_start, window_end = _game_window(startDate, endDate)

    has_boxscore_sq = exists(select(1).where(SportsTeamBoxscore.game_id == SportsGame.id)).label(
        "has_boxscore_flag"
    )
    has_player_stats_sq = exists(
        select(1).where(SportsPlayerBoxscore.game_id == SportsGame.id)
    ).label("has_player_stats_flag")
    play_count_sq = (
        select(func.count(SportsGamePlay.id))
        .where(SportsGamePlay.game_id == SportsGame.id)
        .correlate(SportsGame)
        .scalar_subquery()
        .label("play_count")
    )

    stmt = (
        select(SportsGame, has_boxscore_sq, has_player_stats_sq, play_count_sq)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.team_boxscores).selectinload(SportsTeamBoxscore.team),
            selectinload(SportsGame.player_boxscores).selectinload(SportsPlayerBoxscore.team),
        )
        .where(
            SportsGame.game_date >= window_start,
            SportsGame.game_date < window_end,
            SportsGame.status.notin_((GameStatus.CANCELLED.value, GameStatus.postponed.value)),
        )
    )
    count_stmt = select(func.count(SportsGame.id)).where(
        SportsGame.game_date >= window_start,
        SportsGame.game_date < window_end,
        SportsGame.status.notin_((GameStatus.CANCELLED.value, GameStatus.postponed.value)),
    )

    if league:
        league_codes = [code.upper() for code in league]
        stmt = stmt.where(SportsGame.league.has(SportsLeague.code.in_(league_codes)))
        count_stmt = count_stmt.where(SportsGame.league.has(SportsLeague.code.in_(league_codes)))
    if team:
        pattern = f"%{team}%"
        stmt = stmt.where(_team_filter(pattern))
        count_stmt = count_stmt.where(_team_filter(pattern))

    rows = (
        (
            await session.execute(
                _ordered_games_stmt(stmt, sort).offset(offset).limit(limit)
            )
        )
        .unique()
        .all()
    )
    games = [row[0] for row in rows]
    game_ids = [game.id for game in games]

    latest_play_by_game: dict[int, tuple[int | None, str | None]] = {}
    if game_ids:
        latest_play_stmt = (
            select(
                SportsGamePlay.game_id,
                SportsGamePlay.quarter,
                SportsGamePlay.game_clock,
            )
            .where(SportsGamePlay.game_id.in_(game_ids))
            .order_by(SportsGamePlay.game_id, desc(SportsGamePlay.play_index))
            .distinct(SportsGamePlay.game_id)
        )
        for game_id, quarter, clock in (await session.execute(latest_play_stmt)).all():
            latest_play_by_game[game_id] = (quarter, clock)

    total = int((await session.execute(count_stmt)).scalar_one())
    summaries = [
        _summary(
            row[0],
            has_boxscore=bool(row[1]),
            has_player_stats=bool(row[2]),
            play_count=int(row[3] or 0),
            latest_period=latest_play_by_game.get(row[0].id, (None, None))[0],
            latest_clock=latest_play_by_game.get(row[0].id, (None, None))[1],
        )
        for row in rows
    ]
    with_boxscore_count = sum(1 for row in rows if row[1])
    with_player_stats_count = sum(1 for row in rows if row[2])
    with_pbp_count = sum(1 for row in rows if int(row[3] or 0) > 0)
    next_offset = offset + limit if offset + limit < total else None

    return CatchupGameListResponse(
        games=summaries,
        total=total,
        next_offset=next_offset,
        with_boxscore_count=with_boxscore_count,
        with_player_stats_count=with_player_stats_count,
        with_pbp_count=with_pbp_count,
    )


@router.get(
    "/games/{game_id}",
    response_model=CatchupGameDetailResponse,
    response_model_exclude_none=True,
)
async def get_catchup_game(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> CatchupGameDetailResponse:
    """Return plays, player stats, team stats, and the final/current score."""
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.team_boxscores).selectinload(SportsTeamBoxscore.team),
            selectinload(SportsGame.player_boxscores).selectinload(SportsPlayerBoxscore.team),
            selectinload(SportsGame.plays).selectinload(SportsGamePlay.team),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")

    league_code = game.league.code if game.league else None
    plays = [
        serialize_play_entry(play, league_code)
        for play in sorted(game.plays, key=lambda p: p.play_index)
    ]
    _enrich_detail_plays(
        game_id=game.id,
        plays=plays,
        league_code=league_code,
        home_abbr=game.home_team.abbreviation if game.home_team else None,
        away_abbr=game.away_team.abbreviation if game.away_team else None,
    )
    latest_play = plays[-1] if plays else None
    latest_period = latest_play.quarter if latest_play else None
    latest_clock = latest_play.game_clock if latest_play else None
    period_label_value, live_snapshot = _latest_snapshot(game, latest_period, latest_clock)
    context = build_catchup_context(game, plays=list(game.plays))

    player_stats = [
        serialize_player_stat(player, league_code=league_code)
        for player in game.player_boxscores
    ]
    nhl_skaters = None
    nhl_goalies = None
    mlb_batters = None
    mlb_pitchers = None
    if league_code == "NHL":
        nhl_skaters = []
        nhl_goalies = []
        for player in game.player_boxscores:
            if (player.stats or {}).get("player_role") == "goalie":
                nhl_goalies.append(serialize_nhl_goalie(player))
            else:
                nhl_skaters.append(serialize_nhl_skater(player))
    elif league_code == "MLB":
        mlb_batters = []
        mlb_pitchers = []
        for player in game.player_boxscores:
            if (player.stats or {}).get("player_role") == "pitcher":
                mlb_pitchers.append(serialize_mlb_pitcher(player))
            else:
                mlb_batters.append(serialize_mlb_batter(player))

    meta = CatchupGameMeta(
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
        home_team_abbr=game.home_team.abbreviation if game.home_team else None,
        away_team_abbr=game.away_team.abbreviation if game.away_team else None,
        score=_score_obj(game.home_score, game.away_score),
        status=game.status,
        current_period=latest_period,
        game_clock=latest_clock,
        current_period_label=period_label_value,
        live_snapshot=live_snapshot,
        has_boxscore=bool(game.team_boxscores),
        has_player_stats=bool(game.player_boxscores),
        has_pbp=bool(game.plays),
        play_count=len(game.plays),
        context=context,
        last_scraped_at=game.last_scraped_at,
        last_ingested_at=game.last_ingested_at,
        last_pbp_at=game.last_pbp_at,
        last_boxscore_at=game.last_boxscore_at,
    )

    return CatchupGameDetailResponse(
        game=meta,
        plays=plays,
        player_stats=player_stats,
        nhl_skaters=nhl_skaters,
        nhl_goalies=nhl_goalies,
        mlb_batters=mlb_batters,
        mlb_pitchers=mlb_pitchers,
        team_stats=[
            serialize_team_stat(box, league_code=league_code) for box in game.team_boxscores
        ],
    )


@router.get(
    "/games/{game_id}/context",
    response_model=CatchupGameContextResponse,
    response_model_exclude_none=True,
)
async def get_catchup_game_context(
    game_id: int,
    session: AsyncSession = Depends(get_db),
    enhance: bool = Query(False, description="Use OpenAI to polish the deterministic context."),
) -> CatchupGameContextResponse:
    """Return 2-3 spoiler-safe homepage context sentences for a game."""
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.team_boxscores).selectinload(SportsTeamBoxscore.team),
            selectinload(SportsGame.player_boxscores).selectinload(SportsPlayerBoxscore.team),
            selectinload(SportsGame.plays),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")

    context = build_catchup_context(game, plays=list(game.plays))
    source = "template"
    if enhance:
        context, source = enhance_catchup_context_with_openai(game, context)

    return CatchupGameContextResponse(game_id=game.id, context=context, source=source)
