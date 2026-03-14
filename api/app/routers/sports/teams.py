"""Team endpoints for sports admin."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import or_

from ...db import AsyncSession, get_db
from ...db.sports import SportsGame, SportsLeague, SportsTeam
from .schemas import (
    TeamColorUpdate,
    TeamDetail,
    TeamGameSummary,
    TeamListResponse,
    TeamSocialInfo,
    TeamSummary,
)

router = APIRouter()


@router.get("/teams", response_model=TeamListResponse)
async def list_teams(
    league: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_db),
) -> TeamListResponse:
    """List teams with optional league filter and search."""
    games_as_home = (
        select(func.count())
        .where(SportsGame.home_team_id == SportsTeam.id)
        .correlate(SportsTeam)
        .scalar_subquery()
    )
    games_as_away = (
        select(func.count())
        .where(SportsGame.away_team_id == SportsTeam.id)
        .correlate(SportsTeam)
        .scalar_subquery()
    )

    stmt = select(
        SportsTeam,
        SportsLeague.code.label("league_code"),
        (games_as_home + games_as_away).label("games_count"),
    ).join(
        SportsLeague,
        SportsTeam.league_id == SportsLeague.id,
    )

    if league:
        stmt = stmt.where(func.upper(SportsLeague.code) == league.upper())

    if search:
        search_pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                SportsTeam.name.ilike(search_pattern),
                SportsTeam.short_name.ilike(search_pattern),
                SportsTeam.abbreviation.ilike(search_pattern),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(SportsTeam.name).offset(offset).limit(limit)

    result = await session.execute(stmt)
    rows = result.all()

    teams = [
        TeamSummary(
            id=row.SportsTeam.id,
            name=row.SportsTeam.name,
            shortName=row.SportsTeam.short_name,
            abbreviation=row.SportsTeam.abbreviation,
            leagueCode=row.league_code,
            gamesCount=row.games_count or 0,
            colorLightHex=row.SportsTeam.color_light_hex,
            colorDarkHex=row.SportsTeam.color_dark_hex,
        )
        for row in rows
    ]

    return TeamListResponse(teams=teams, total=total)


@router.get("/teams/{team_id}", response_model=TeamDetail)
async def get_team(team_id: int, session: AsyncSession = Depends(get_db)) -> TeamDetail:
    """Get team detail with recent games."""
    team = await session.get(SportsTeam, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    league = await session.get(SportsLeague, team.league_id)

    home_games = (
        select(SportsGame)
        .where(SportsGame.home_team_id == team_id)
        .options(selectinload(SportsGame.away_team))
    )
    away_games = (
        select(SportsGame)
        .where(SportsGame.away_team_id == team_id)
        .options(selectinload(SportsGame.home_team))
    )

    home_result = await session.execute(
        home_games.order_by(desc(SportsGame.game_date)).limit(10)
    )
    away_result = await session.execute(
        away_games.order_by(desc(SportsGame.game_date)).limit(10)
    )

    recent_games: list[TeamGameSummary] = []

    for game in home_result.scalars():
        score = f"{game.home_score or 0}-{game.away_score or 0}"
        result = (
            "W"
            if (game.home_score or 0) > (game.away_score or 0)
            else "L"
            if (game.home_score or 0) < (game.away_score or 0)
            else "-"
        )
        recent_games.append(
            TeamGameSummary(
                id=game.id,
                gameDate=game.game_date.isoformat() if game.game_date else "",
                opponent=game.away_team.name if game.away_team else "Unknown",
                isHome=True,
                score=score,
                result=result,
            )
        )

    for game in away_result.scalars():
        score = f"{game.away_score or 0}-{game.home_score or 0}"
        result = (
            "W"
            if (game.away_score or 0) > (game.home_score or 0)
            else "L"
            if (game.away_score or 0) < (game.home_score or 0)
            else "-"
        )
        recent_games.append(
            TeamGameSummary(
                id=game.id,
                gameDate=game.game_date.isoformat() if game.game_date else "",
                opponent=game.home_team.name if game.home_team else "Unknown",
                isHome=False,
                score=score,
                result=result,
            )
        )

    recent_games.sort(
        key=lambda g: g.game_date, reverse=True
    )
    recent_games = recent_games[:20]

    return TeamDetail(
        id=team.id,
        name=team.name,
        shortName=team.short_name,
        abbreviation=team.abbreviation,
        leagueCode=league.code if league else "UNK",
        location=team.location,
        externalRef=team.external_ref,
        xHandle=team.x_handle,
        xProfileUrl=f"https://x.com/{team.x_handle}" if team.x_handle else None,
        colorLightHex=team.color_light_hex,
        colorDarkHex=team.color_dark_hex,
        recentGames=recent_games,
    )


@router.get("/teams/{team_id}/social", response_model=TeamSocialInfo)
async def get_team_social_info(
    team_id: int, session: AsyncSession = Depends(get_db)
) -> TeamSocialInfo:
    """Get team's social media info including X handle."""
    team = await session.get(SportsTeam, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    return TeamSocialInfo(
        teamId=team.id,
        abbreviation=team.abbreviation or "",
        xHandle=team.x_handle,
        xProfileUrl=f"https://x.com/{team.x_handle}" if team.x_handle else None,
    )


@router.patch("/teams/{team_id}/colors", response_model=TeamDetail)
async def update_team_colors(
    team_id: int,
    body: TeamColorUpdate,
    session: AsyncSession = Depends(get_db),
) -> TeamDetail:
    """Update team colors (light and dark hex values)."""
    team = await session.get(SportsTeam, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    if "color_light_hex" in body.model_fields_set:
        team.color_light_hex = body.color_light_hex
    if "color_dark_hex" in body.model_fields_set:
        team.color_dark_hex = body.color_dark_hex

    await session.commit()
    await session.refresh(team)

    league = await session.get(SportsLeague, team.league_id)

    # Build recent games for the response
    home_games = (
        select(SportsGame)
        .where(SportsGame.home_team_id == team_id)
        .options(selectinload(SportsGame.away_team))
    )
    away_games = (
        select(SportsGame)
        .where(SportsGame.away_team_id == team_id)
        .options(selectinload(SportsGame.home_team))
    )

    home_result = await session.execute(
        home_games.order_by(desc(SportsGame.game_date)).limit(10)
    )
    away_result = await session.execute(
        away_games.order_by(desc(SportsGame.game_date)).limit(10)
    )

    recent_games: list[TeamGameSummary] = []

    for game in home_result.scalars():
        score = f"{game.home_score or 0}-{game.away_score or 0}"
        result = (
            "W"
            if (game.home_score or 0) > (game.away_score or 0)
            else "L"
            if (game.home_score or 0) < (game.away_score or 0)
            else "-"
        )
        recent_games.append(
            TeamGameSummary(
                id=game.id,
                gameDate=game.game_date.isoformat() if game.game_date else "",
                opponent=game.away_team.name if game.away_team else "Unknown",
                isHome=True,
                score=score,
                result=result,
            )
        )

    for game in away_result.scalars():
        score = f"{game.away_score or 0}-{game.home_score or 0}"
        result = (
            "W"
            if (game.away_score or 0) > (game.home_score or 0)
            else "L"
            if (game.away_score or 0) < (game.home_score or 0)
            else "-"
        )
        recent_games.append(
            TeamGameSummary(
                id=game.id,
                gameDate=game.game_date.isoformat() if game.game_date else "",
                opponent=game.home_team.name if game.home_team else "Unknown",
                isHome=False,
                score=score,
                result=result,
            )
        )

    recent_games.sort(key=lambda g: g.game_date, reverse=True)
    recent_games = recent_games[:20]

    return TeamDetail(
        id=team.id,
        name=team.name,
        shortName=team.short_name,
        abbreviation=team.abbreviation,
        leagueCode=league.code if league else "UNK",
        location=team.location,
        externalRef=team.external_ref,
        xHandle=team.x_handle,
        xProfileUrl=f"https://x.com/{team.x_handle}" if team.x_handle else None,
        colorLightHex=team.color_light_hex,
        colorDarkHex=team.color_dark_hex,
        recentGames=recent_games,
    )
