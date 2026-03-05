"""Odds models: game odds and FairBet work table."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .base import Base
from .sports import SportsGame


class SportsGameOdds(Base):
    """Odds data for games (multiple books/markets per game)."""

    __tablename__ = "sports_game_odds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    book: Mapped[str] = mapped_column(String(50), nullable=False)
    market_type: Mapped[str] = mapped_column(String(80), nullable=False)
    side: Mapped[str | None] = mapped_column(String(200), nullable=True)
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_closing_line: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    market_category: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'mainline'")
    )
    player_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
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

    game: Mapped[SportsGame] = relationship("SportsGame", back_populates="odds")

    __table_args__ = (
        Index(
            "uq_sports_game_odds_identity",
            "game_id",
            "book",
            "market_type",
            "side",
            "is_closing_line",
            unique=True,
        ),
    )


class FairbetGameOddsWork(Base):
    """FairBet work table: derived, disposable, upserted odds for comparison.

    This table stores one row per (bet x book) for non-completed games.
    It enables FairBet to compare odds across many books for each bet definition.
    """

    __tablename__ = "fairbet_game_odds_work"

    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_games.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    market_key: Mapped[str] = mapped_column(
        String(80), primary_key=True, nullable=False
    )
    selection_key: Mapped[str] = mapped_column(
        String, primary_key=True, nullable=False
    )
    line_value: Mapped[float] = mapped_column(
        Float, primary_key=True, nullable=False, default=0.0
    )
    book: Mapped[str] = mapped_column(
        String(50), primary_key=True, nullable=False
    )
    price: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    market_category: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'mainline'")
    )
    player_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    game: Mapped[SportsGame] = relationship("SportsGame")

    __table_args__ = (
        Index("idx_fairbet_odds_game", "game_id"),
        Index("idx_fairbet_odds_observed", "observed_at"),
    )


class ClosingLine(Base):
    """Durable closing-line snapshot captured when a game transitions to LIVE.

    One row per (game, provider, market_key, selection, line_value).
    Used as the stable baseline for CLV tracking and FairBet Live comparisons.
    """

    __tablename__ = "closing_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    league: Mapped[str] = mapped_column(String(10), nullable=False)
    market_key: Mapped[str] = mapped_column(String(80), nullable=False)
    selection: Mapped[str] = mapped_column(String(200), nullable=False)
    line_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_american: Mapped[float] = mapped_column(Float, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'closing'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    game: Mapped[SportsGame] = relationship("SportsGame")

    __table_args__ = (
        Index(
            "uq_closing_lines_identity",
            "game_id",
            "provider",
            "market_key",
            "selection",
            "line_value",
            unique=True,
        ),
    )
