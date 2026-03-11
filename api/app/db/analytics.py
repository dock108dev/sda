"""Analytics configuration, training job, backtest, and prediction outcome models.

Stores feature loadout configurations, training job tracking,
backtest job tracking, and prediction outcomes for calibration
in the database for the analytics models page.
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

    Created when a user kicks off training from the models page.
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


class AnalyticsPredictionOutcome(Base):
    """Stores individual game predictions and their eventual outcomes.

    Created when a batch simulation completes. The outcome columns are
    filled in later by the auto-record task when the game reaches
    ``final`` status.
    """

    __tablename__ = "analytics_prediction_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sport: Mapped[str] = mapped_column(String(50), nullable=False)
    batch_sim_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Prediction
    home_team: Mapped[str] = mapped_column(String(100), nullable=False)
    away_team: Mapped[str] = mapped_column(String(100), nullable=False)
    predicted_home_wp: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_away_wp: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_home_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_away_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    game_date: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Outcome (filled when game goes final)
    actual_home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_win_actual: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    correct_winner: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalyticsDegradationAlert(Base):
    """Records model degradation alerts when Brier score trends upward.

    Generated by the ``check_model_degradation`` task after outcomes
    are recorded. Compares a recent window of predictions against a
    baseline window to detect accuracy drops.
    """

    __tablename__ = "analytics_degradation_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sport: Mapped[str] = mapped_column(String(50), nullable=False)
    alert_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="brier_degradation"
    )

    # Window metrics
    baseline_brier: Mapped[float] = mapped_column(Float, nullable=False)
    recent_brier: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    recent_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_count: Mapped[int] = mapped_column(Integer, nullable=False)
    delta_brier: Mapped[float] = mapped_column(Float, nullable=False)
    delta_accuracy: Mapped[float] = mapped_column(Float, nullable=False)

    # Alert severity: info, warning, critical
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
