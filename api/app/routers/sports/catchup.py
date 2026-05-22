"""Minimal Scroll Down Sports catch-up endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, exists, func, or_, select
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
from ...utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc
from .common import serialize_play_entry, serialize_player_stat, serialize_team_stat
from .schemas.catchup import (
    CatchupGameContextResponse,
    CatchupGameDetailResponse,
    CatchupGameListResponse,
    CatchupGameMeta,
    CatchupGameSummary,
)
from .schemas.common import LiveSnapshot, _score_obj

router = APIRouter()

_DEFAULT_LOOKBACK_HOURS = 72
_DEFAULT_LOOKAHEAD_HOURS = 48


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
            score=_score_obj(game.home_score, game.away_score),
            current_period=latest_period,
            game_clock=latest_clock,
        ),
    )


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
    context = build_catchup_context(game)
    return CatchupGameSummary(
        id=game.id,
        league_code=game.league.code if game.league else "UNKNOWN",
        game_date=game.game_date,
        local_game_date=getattr(game, "local_game_date", None),
        home_team=game.home_team.name if game.home_team else "Unknown",
        away_team=game.away_team.name if game.away_team else "Unknown",
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
        context=context,
    )


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
                stmt.order_by(SportsGame.game_date.asc()).offset(offset).limit(limit)
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
    latest_play = plays[-1] if plays else None
    latest_period = latest_play.quarter if latest_play else None
    latest_clock = latest_play.game_clock if latest_play else None
    period_label_value, live_snapshot = _latest_snapshot(game, latest_period, latest_clock)
    context = build_catchup_context(game, plays=list(game.plays))

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
        player_stats=[
            serialize_player_stat(player, league_code=league_code)
            for player in game.player_boxscores
        ],
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
