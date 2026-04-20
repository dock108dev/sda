"""Golf domain ORM models.

Separate from the team-sport models in ``sports.py``. Golf uses
tournaments (multi-day, player-vs-field) instead of games, and
DataGolf's ``dg_id`` as the canonical player identifier.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GolfPlayer(Base):
    __tablename__ = "golf_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dg_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    player_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(10))
    amateur: Mapped[bool] = mapped_column(Boolean, default=False)
    dk_id: Mapped[int | None] = mapped_column(Integer)
    fd_id: Mapped[int | None] = mapped_column(Integer)
    yahoo_id: Mapped[int | None] = mapped_column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfTournament(Base):
    __tablename__ = "golf_tournaments"
    __table_args__ = (
        UniqueConstraint("event_id", "tour", name="uq_golf_tournament_event_tour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tour: Mapped[str] = mapped_column(String(20), nullable=False)
    event_name: Mapped[str] = mapped_column(String(300), nullable=False)
    course: Mapped[str | None] = mapped_column(String(300))
    course_key: Mapped[str | None] = mapped_column(String(100))
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date | None] = mapped_column(Date)
    season: Mapped[int | None] = mapped_column(Integer)
    purse: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    country: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    current_round: Mapped[int | None] = mapped_column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfTournamentField(Base):
    __tablename__ = "golf_tournament_fields"
    __table_args__ = (
        UniqueConstraint("tournament_id", "dg_id", name="uq_golf_field_entry"),
        Index("idx_golf_field_tournament", "tournament_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    dg_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False)
    player_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="active")
    tee_time_r1: Mapped[str | None] = mapped_column(String(20))
    tee_time_r2: Mapped[str | None] = mapped_column(String(20))
    early_late: Mapped[str | None] = mapped_column(String(10))
    course: Mapped[str | None] = mapped_column(String(200))
    dk_salary: Mapped[int | None] = mapped_column(Integer)
    fd_salary: Mapped[int | None] = mapped_column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfLeaderboard(Base):
    __tablename__ = "golf_leaderboard"
    __table_args__ = (
        UniqueConstraint("tournament_id", "dg_id", name="uq_golf_leaderboard_entry"),
        Index("idx_golf_leaderboard_tournament", "tournament_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    dg_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False)
    player_name: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[int | None] = mapped_column(Integer)
    total_score: Mapped[int | None] = mapped_column(Integer)
    today_score: Mapped[int | None] = mapped_column(Integer)
    thru: Mapped[int | None] = mapped_column(Integer)
    total_strokes: Mapped[int | None] = mapped_column(Integer)
    r1: Mapped[int | None] = mapped_column(Integer)
    r2: Mapped[int | None] = mapped_column(Integer)
    r3: Mapped[int | None] = mapped_column(Integer)
    r4: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="active")
    sg_total: Mapped[float | None] = mapped_column(Float)
    sg_ott: Mapped[float | None] = mapped_column(Float)
    sg_app: Mapped[float | None] = mapped_column(Float)
    sg_arg: Mapped[float | None] = mapped_column(Float)
    sg_putt: Mapped[float | None] = mapped_column(Float)
    win_prob: Mapped[float | None] = mapped_column(Float)
    top_5_prob: Mapped[float | None] = mapped_column(Float)
    top_10_prob: Mapped[float | None] = mapped_column(Float)
    make_cut_prob: Mapped[float | None] = mapped_column(Float)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfRound(Base):
    __tablename__ = "golf_rounds"
    __table_args__ = (
        UniqueConstraint("tournament_id", "dg_id", "round_num", name="uq_golf_round"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    dg_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False)
    round_num: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    strokes: Mapped[int | None] = mapped_column(Integer)
    sg_total: Mapped[float | None] = mapped_column(Float)
    sg_ott: Mapped[float | None] = mapped_column(Float)
    sg_app: Mapped[float | None] = mapped_column(Float)
    sg_arg: Mapped[float | None] = mapped_column(Float)
    sg_putt: Mapped[float | None] = mapped_column(Float)
    driving_dist: Mapped[float | None] = mapped_column(Float)
    driving_acc: Mapped[float | None] = mapped_column(Float)
    gir: Mapped[float | None] = mapped_column(Float)
    scrambling: Mapped[float | None] = mapped_column(Float)
    prox: Mapped[float | None] = mapped_column(Float)
    putts_per_round: Mapped[float | None] = mapped_column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfPlayerStats(Base):
    __tablename__ = "golf_player_stats"
    __table_args__ = (
        UniqueConstraint("dg_id", "period", name="uq_golf_player_stats"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dg_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False)
    period: Mapped[str] = mapped_column(String(30), default="current")
    sg_total: Mapped[float | None] = mapped_column(Float)
    sg_ott: Mapped[float | None] = mapped_column(Float)
    sg_app: Mapped[float | None] = mapped_column(Float)
    sg_arg: Mapped[float | None] = mapped_column(Float)
    sg_putt: Mapped[float | None] = mapped_column(Float)
    driving_dist: Mapped[float | None] = mapped_column(Float)
    driving_acc: Mapped[float | None] = mapped_column(Float)
    dg_rank: Mapped[int | None] = mapped_column(Integer)
    owgr: Mapped[int | None] = mapped_column(Integer)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfTournamentOdds(Base):
    __tablename__ = "golf_tournament_odds"
    __table_args__ = (
        UniqueConstraint("tournament_id", "dg_id", "book", "market", name="uq_golf_odds"),
        Index("idx_golf_odds_tournament", "tournament_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    dg_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False)
    player_name: Mapped[str | None] = mapped_column(String(200))
    book: Mapped[str] = mapped_column(String(50), nullable=False)
    market: Mapped[str] = mapped_column(String(30), nullable=False)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    implied_prob: Mapped[float | None] = mapped_column(Float)
    dg_prob: Mapped[float | None] = mapped_column(Float)
    observed_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfDFSProjection(Base):
    __tablename__ = "golf_dfs_projections"
    __table_args__ = (
        UniqueConstraint("tournament_id", "dg_id", "site", name="uq_golf_dfs_projection"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    dg_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False)
    player_name: Mapped[str | None] = mapped_column(String(200))
    site: Mapped[str] = mapped_column(String(30), nullable=False)
    salary: Mapped[int | None] = mapped_column(Integer)
    projected_points: Mapped[float | None] = mapped_column(Float)
    projected_ownership: Mapped[float | None] = mapped_column(Float)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
