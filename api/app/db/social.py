"""Social media models: posts and accounts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .base import Base
from .sports import SportsGame, SportsLeague, SportsTeam


class MappingStatus(str, Enum):
    """Status of a team social post's mapping to a game."""

    unmapped = "unmapped"
    mapped = "mapped"
    no_game = "no_game"


class TeamSocialPost(Base):
    """Team-centric social posts.

    Posts are collected per-team, then mapped to games based on posted_at.
    """

    __tablename__ = "team_social_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(
        String(20), server_default="x", nullable=False
    )
    external_post_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True
    )
    post_url: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    tweet_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    likes_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retweets_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replies_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_video: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)

    game_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sports_games.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mapping_status: Mapped[str] = mapped_column(
        String(20), server_default="unmapped", nullable=False, index=True
    )
    game_phase: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="unknown", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    team: Mapped[SportsTeam] = relationship("SportsTeam")
    game: Mapped[SportsGame | None] = relationship("SportsGame")

    __table_args__ = (
        Index("idx_team_social_posts_team", "team_id"),
        Index("idx_team_social_posts_posted_at", "posted_at"),
        Index("idx_team_social_posts_mapping_status", "mapping_status"),
        Index("idx_team_social_posts_game", "game_id"),
        Index("idx_team_social_posts_team_status", "team_id", "mapping_status"),
    )


class TeamSocialAccount(Base):
    """Registry of official team social accounts."""

    __tablename__ = "team_social_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    league_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_leagues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    handle: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    team: Mapped[SportsTeam] = relationship(
        "SportsTeam", back_populates="social_accounts"
    )
    league: Mapped[SportsLeague] = relationship("SportsLeague")

    __table_args__ = (
        UniqueConstraint(
            "platform", "handle", name="uq_team_social_accounts_platform_handle"
        ),
        UniqueConstraint(
            "team_id", "platform", name="uq_team_social_accounts_team_platform"
        ),
        Index("idx_team_social_accounts_league", "league_id"),
    )


class SocialAccountPoll(Base):
    """Cache metadata for social polling requests."""

    __tablename__ = "social_account_polls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    handle: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    posts_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rate_limited_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "platform",
            "handle",
            "window_start",
            "window_end",
            name="uq_social_account_poll_window",
        ),
        Index(
            "idx_social_account_polls_handle_window",
            "handle",
            "window_start",
            "window_end",
        ),
    )
