"""Analytics configuration, training job, and backtest models.

Stores feature loadout configurations, training job tracking,
and backtest job tracking in the database for the analytics workbench.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .base import Base


class AnalyticsFeatureConfig(Base):
    """A named feature loadout for ML model training.

    Each loadout defines which features are enabled, their weights,
    and which sport/model_type they apply to. Users can create,
    clone, and edit loadouts via the admin UI.
    """

    __tablename__ = "analytics_feature_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    sport: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # JSONB array of {name, enabled, weight} dicts
    features: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship to training jobs that used this config
    training_jobs: Mapped[list["AnalyticsTrainingJob"]] = relationship(
        back_populates="feature_config",
    )


class AnalyticsTrainingJob(Base):
    """Tracks an async model training job.

    Created when a user kicks off training from the workbench.
    Updated by the Celery task as it progresses.
    """

    __tablename__ = "analytics_training_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_config_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("analytics_feature_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sport: Mapped[str] = mapped_column(String(50), nullable=False)
    model_type: Mapped[str] = mapped_column(String(100), nullable=False)
    algorithm: Mapped[str] = mapped_column(
        String(100), nullable=False, default="gradient_boosting"
    )

    # Training parameters
    date_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    test_split: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    random_state: Mapped[int] = mapped_column(Integer, nullable=False, default=42)
    rolling_window: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    # Job status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending, running, completed, failed
    celery_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Results (populated on completion)
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    train_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feature_names: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    feature_importance: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    feature_config: Mapped[AnalyticsFeatureConfig | None] = relationship(
        back_populates="training_jobs",
    )


class AnalyticsBacktestJob(Base):
    """Tracks an async backtest job.

    Created when a user runs a backtest from the model detail page.
    The Celery task loads the model artifact, runs predictions against
    games in the date range, and stores per-game results.
    """

    __tablename__ = "analytics_backtest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sport: Mapped[str] = mapped_column(String(50), nullable=False)
    model_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Backtest parameters
    date_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rolling_window: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    # Job status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending, running, completed, failed
    celery_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Results (populated on completion)
    game_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    predictions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AnalyticsBatchSimJob(Base):
    """Tracks a batch simulation job across upcoming games.

    Created when a user triggers "Simulate Upcoming Games" from the
    simulator page. The Celery task runs Monte Carlo sims on each
    game and stores per-game results.
    """

    __tablename__ = "analytics_batch_sim_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sport: Mapped[str] = mapped_column(String(50), nullable=False)
    probability_mode: Mapped[str] = mapped_column(
        String(50), nullable=False, default="ml"
    )
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    rolling_window: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    date_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_end: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Job status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Results
    game_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
