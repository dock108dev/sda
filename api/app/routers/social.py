"""API endpoints for game social posts (X/Twitter embeds)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db import AsyncSession, get_db
from ..db.social import TeamSocialAccount, TeamSocialPost
from ..db.sports import SportsGame, SportsLeague, SportsTeam

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)

router = APIRouter(prefix="/api/social", tags=["social"])


# ────────────────────────────────────────────────────────────────────────────────
# Response Models
# ────────────────────────────────────────────────────────────────────────────────


class SocialPostResponse(BaseModel):
    """Single social post for timeline display."""

    model_config = _ALIAS_CFG

    id: int
    game_id: int
    team_id: str  # Team abbreviation for frontend
    post_url: str
    posted_at: datetime
    has_video: bool
    # Content fields for custom X embed display
    video_url: str | None = None
    image_url: str | None = None
    tweet_text: str | None = None
    source_handle: str | None = None
    media_type: str | None = None


class SocialPostListResponse(BaseModel):
    """List of social posts."""

    posts: list[SocialPostResponse]
    total: int


class SocialPostCreateRequest(BaseModel):
    """Request to create a new social post."""

    game_id: int = Field(..., alias="gameId")
    team_abbreviation: str = Field(..., alias="teamAbbreviation")
    post_url: str = Field(..., alias="postUrl")
    posted_at: datetime = Field(..., alias="postedAt")
    has_video: bool = Field(False, alias="hasVideo")
    # Content fields for custom X embed display
    video_url: str | None = Field(None, alias="videoUrl")
    image_url: str | None = Field(None, alias="imageUrl")
    tweet_text: str | None = Field(None, alias="tweetText")
    source_handle: str | None = Field(None, alias="sourceHandle")
    media_type: str | None = Field(None, alias="mediaType")


class SocialPostBulkCreateRequest(BaseModel):
    """Bulk create social posts."""

    posts: list[SocialPostCreateRequest]


class SocialAccountResponse(BaseModel):
    """Social account registry entry."""

    id: int
    team_id: int = Field(alias="teamId")
    league_code: str = Field(alias="leagueCode")
    platform: str
    handle: str
    is_active: bool = Field(alias="isActive")


class SocialAccountListResponse(BaseModel):
    """List of social account registry entries."""

    accounts: list[SocialAccountResponse]
    total: int


class SocialAccountUpsertRequest(BaseModel):
    """Request to upsert a social account registry entry."""

    team_id: int = Field(..., alias="teamId")
    platform: str = Field(default="x")
    handle: str
    is_active: bool = Field(default=True, alias="isActive")


# ────────────────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────────────────


def _serialize_post(post: TeamSocialPost) -> SocialPostResponse:
    """Serialize a social post to API response."""
    return SocialPostResponse(
        id=post.id,
        game_id=post.game_id,
        team_id=post.team.abbreviation if post.team else "UNK",
        post_url=post.post_url,
        posted_at=post.posted_at,
        has_video=post.has_video,
        video_url=post.video_url,
        image_url=post.image_url,
        tweet_text=post.tweet_text,
        source_handle=post.source_handle or (post.team.x_handle if post.team else None),
        media_type=post.media_type,
    )


def _serialize_account(account: TeamSocialAccount) -> SocialAccountResponse:
    """Serialize a social account registry entry to API response."""
    league_code = account.league.code if account.league else "UNK"
    return SocialAccountResponse(
        id=account.id,
        teamId=account.team_id,
        leagueCode=league_code,
        platform=account.platform,
        handle=account.handle,
        isActive=account.is_active,
    )


@router.get("/posts", response_model=SocialPostListResponse)
async def list_social_posts(
    game_id: int | None = Query(None, alias="game_id"),
    team_id: str | None = Query(None, alias="team_id"),
    start_date: datetime | None = Query(None, alias="start_date"),
    end_date: datetime | None = Query(None, alias="end_date"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> SocialPostListResponse:
    """
    List social posts with optional filters.

    - game_id: Filter by specific game
    - team_id: Filter by team abbreviation (e.g., "GSW", "LAL")
    - start_date/end_date: Filter by posted_at timestamp
    """
    stmt = (
        select(TeamSocialPost)
        .options(selectinload(TeamSocialPost.team))
        .where(TeamSocialPost.mapping_status == "mapped")
    )

    if game_id is not None:
        stmt = stmt.where(TeamSocialPost.game_id == game_id)

    if team_id is not None:
        # Join to team and filter by abbreviation
        stmt = stmt.where(
            TeamSocialPost.team.has(
                SportsTeam.abbreviation.ilike(team_id)
            )
        )

    if start_date is not None:
        stmt = stmt.where(TeamSocialPost.posted_at >= start_date)

    if end_date is not None:
        stmt = stmt.where(TeamSocialPost.posted_at <= end_date)

    # Count total before pagination
    from sqlalchemy import func

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    # Apply ordering and pagination
    stmt = (
        stmt.order_by(TeamSocialPost.posted_at.asc())
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(stmt)
    posts = result.scalars().all()

    return SocialPostListResponse(
        posts=[_serialize_post(post) for post in posts],
        total=total,
    )


@router.get("/accounts", response_model=SocialAccountListResponse)
async def list_social_accounts(
    league: str | None = Query(None),
    team_id: int | None = Query(None, alias="team_id"),
    platform: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> SocialAccountListResponse:
    """List social account registry entries with optional filters."""
    stmt = select(TeamSocialAccount).options(
        selectinload(TeamSocialAccount.league)
    )

    if league:
        stmt = stmt.join(SportsLeague).where(
            SportsLeague.code.ilike(league)
        )

    if team_id is not None:
        stmt = stmt.where(TeamSocialAccount.team_id == team_id)

    if platform:
        stmt = stmt.where(TeamSocialAccount.platform == platform)

    from sqlalchemy import func

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(TeamSocialAccount.id).offset(offset).limit(limit)
    result = await session.execute(stmt)
    accounts = result.scalars().all()

    return SocialAccountListResponse(
        accounts=[_serialize_account(account) for account in accounts],
        total=total,
    )


@router.post(
    "/accounts",
    response_model=SocialAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_social_account(
    payload: SocialAccountUpsertRequest,
    session: AsyncSession = Depends(get_db),
) -> SocialAccountResponse:
    """Create or update a social account registry entry."""
    team = await session.get(SportsTeam, payload.team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    existing_stmt = select(TeamSocialAccount).where(
        TeamSocialAccount.team_id == payload.team_id,
        TeamSocialAccount.platform == payload.platform,
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()

    if existing:
        existing.handle = payload.handle
        existing.is_active = payload.is_active
        await session.flush()
        await session.refresh(existing, attribute_names=["league"])
        return _serialize_account(existing)

    account = TeamSocialAccount(
        team_id=payload.team_id,
        league_id=team.league_id,
        platform=payload.platform,
        handle=payload.handle,
        is_active=payload.is_active,
    )
    session.add(account)
    await session.flush()
    await session.refresh(account, attribute_names=["league"])
    return _serialize_account(account)


@router.get("/posts/game/{game_id}", response_model=SocialPostListResponse)
async def get_posts_for_game(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> SocialPostListResponse:
    """Get all social posts for a specific game, sorted by posted_at."""
    stmt = (
        select(TeamSocialPost)
        .options(selectinload(TeamSocialPost.team))
        .where(
            TeamSocialPost.game_id == game_id,
            TeamSocialPost.mapping_status == "mapped",
        )
        .order_by(TeamSocialPost.posted_at.asc())
    )

    result = await session.execute(stmt)
    posts = result.scalars().all()

    return SocialPostListResponse(
        posts=[_serialize_post(post) for post in posts],
        total=len(posts),
    )


@router.post(
    "/posts", response_model=SocialPostResponse, status_code=status.HTTP_201_CREATED
)
async def create_social_post(
    payload: SocialPostCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> SocialPostResponse:
    """Create a new social post linked to a game."""
    game = await session.get(SportsGame, payload.game_id)
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game {payload.game_id} not found",
        )

    team_stmt = select(SportsTeam).where(
        SportsTeam.abbreviation.ilike(payload.team_abbreviation)
    )
    result = await session.execute(team_stmt)
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team with abbreviation '{payload.team_abbreviation}' not found",
        )

    # Check for duplicate URL
    existing_stmt = select(TeamSocialPost).where(
        TeamSocialPost.post_url == payload.post_url
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Post URL already exists",
        )

    post = TeamSocialPost(
        game_id=payload.game_id,
        team_id=team.id,
        post_url=payload.post_url,
        posted_at=payload.posted_at,
        has_video=payload.has_video,
        video_url=payload.video_url,
        image_url=payload.image_url,
        tweet_text=payload.tweet_text,
        source_handle=payload.source_handle,
        media_type=payload.media_type,
        mapping_status="mapped",
    )
    session.add(post)
    await session.flush()
    await session.refresh(post, attribute_names=["team"])

    return _serialize_post(post)


@router.post(
    "/posts/bulk",
    response_model=SocialPostListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_create_social_posts(
    payload: SocialPostBulkCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> SocialPostListResponse:
    """Bulk create social posts. Skips duplicates by post_url."""
    created_posts: list[TeamSocialPost] = []

    # Pre-fetch all teams by abbreviation
    abbrevs = list({p.team_abbreviation.upper() for p in payload.posts})
    team_stmt = select(SportsTeam).where(
        SportsTeam.abbreviation.in_(abbrevs)
    )
    team_result = await session.execute(team_stmt)
    teams_by_abbrev = {t.abbreviation.upper(): t for t in team_result.scalars()}

    # Pre-fetch existing URLs to skip
    urls = [p.post_url for p in payload.posts]
    existing_stmt = select(TeamSocialPost.post_url).where(
        TeamSocialPost.post_url.in_(urls)
    )
    existing_urls = set((await session.execute(existing_stmt)).scalars())

    for post_data in payload.posts:
        if post_data.post_url in existing_urls:
            continue  # Skip duplicate

        team = teams_by_abbrev.get(post_data.team_abbreviation.upper())
        if not team:
            continue  # Skip unknown team

        post = TeamSocialPost(
            game_id=post_data.game_id,
            team_id=team.id,
            post_url=post_data.post_url,
            posted_at=post_data.posted_at,
            has_video=post_data.has_video,
            video_url=post_data.video_url,
            image_url=post_data.image_url,
            tweet_text=post_data.tweet_text,
            source_handle=post_data.source_handle,
            media_type=post_data.media_type,
            mapping_status="mapped",
        )
        session.add(post)
        created_posts.append(post)

    await session.flush()

    # Refresh to load team relationships
    for post in created_posts:
        await session.refresh(post, attribute_names=["team"])

    return SocialPostListResponse(
        posts=[_serialize_post(post) for post in created_posts],
        total=len(created_posts),
    )


@router.delete("/posts/{post_id}")
async def delete_social_post(
    post_id: int,
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a social post."""
    post = await session.get(TeamSocialPost, post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    await session.delete(post)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
