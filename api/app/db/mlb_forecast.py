"""MLB daily forecast work table.

Stores hourly-refreshed predictions for upcoming MLB games.
One row per game, upserted each hour with the latest simulation results
and current market line analysis. Designed for direct querying by
downstream consuming apps.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MlbDailyForecast(Base):
    """Rolling MLB game prediction, refreshed hourly."""

    __tablename__ = "mlb_daily_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(Integer, nullable=False)
    game_date: Mapped[str] = mapped_column(String(20), nullable=False)

    # Teams
    home_team: Mapped[str] = mapped_column(String(200), nullable=False)
    away_team: Mapped[str] = mapped_column(String(200), nullable=False)
    home_team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    away_team_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Simulation results
    home_win_prob: Mapped[float] = mapped_column(Float, nullable=False)
    away_win_prob: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_home_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_away_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sim_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    sim_wp_std_dev: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_std_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_std_away: Mapped[float | None] = mapped_column(Float, nullable=True)
    profile_games_home: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_games_away: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Line analysis (flattened for queryability)
    market_home_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_away_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_home_wp: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_away_wp: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_home_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_away_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_ev_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_ev_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    line_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    line_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Metadata
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    feature_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Timestamps
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("game_id", name="uq_mlb_daily_forecasts_game_id"),
        Index("ix_mlb_daily_forecasts_game_date", "game_date"),
        Index("ix_mlb_daily_forecasts_date_edge", "game_date", "home_edge"),
    )
