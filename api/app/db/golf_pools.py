"""Golf pool ORM models.

Manages pick-em pool definitions, entries, picks, and scoring.
References the golf domain tables for tournament and player data.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GolfPool(Base):
    __tablename__ = "golf_pools"
    __table_args__ = (
        UniqueConstraint("tournament_id", "code", name="uq_golf_pool_tournament_code"),
        Index("idx_golf_pools_tournament", "tournament_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    club_code: Mapped[str] = mapped_column(String(100), nullable=False)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    rules_json = Column(JSONB)
    entry_open_at = Column(DateTime(timezone=True))
    entry_deadline = Column(DateTime(timezone=True))
    scoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_entries_per_email: Mapped[int | None] = mapped_column(Integer)
    require_upload: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_self_service_entry: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfPoolBucket(Base):
    __tablename__ = "golf_pool_buckets"
    __table_args__ = (
        UniqueConstraint("pool_id", "bucket_number", name="uq_golf_pool_bucket"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_pools.id", ondelete="CASCADE"), nullable=False)
    bucket_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GolfPoolBucketPlayer(Base):
    __tablename__ = "golf_pool_bucket_players"
    __table_args__ = (
        UniqueConstraint("bucket_id", "dg_id", name="uq_golf_pool_bucket_player"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_pool_buckets.id", ondelete="CASCADE"), nullable=False)
    dg_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False)
    player_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GolfPoolEntry(Base):
    __tablename__ = "golf_pool_entries"
    __table_args__ = (
        Index("idx_golf_pool_entries_pool_email", "pool_id", "email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_pools.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(300), nullable=False)
    entry_name: Mapped[str | None] = mapped_column(String(200))
    entry_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    source: Mapped[str] = mapped_column(String(30), default="self_service")
    upload_filename: Mapped[str | None] = mapped_column(String(500))
    submitted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfPoolEntryPick(Base):
    __tablename__ = "golf_pool_entry_picks"
    __table_args__ = (
        UniqueConstraint("entry_id", "pick_slot", name="uq_golf_pool_entry_pick"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_pool_entries.id", ondelete="CASCADE"), nullable=False)
    dg_id: Mapped[int] = mapped_column(Integer, nullable=False)
    player_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    pick_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket_number: Mapped[int | None] = mapped_column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GolfPoolEntryScorePlayer(Base):
    __tablename__ = "golf_pool_entry_score_players"
    __table_args__ = (
        UniqueConstraint("entry_id", "dg_id", name="uq_golf_pool_entry_score_player"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_pools.id", ondelete="CASCADE"), nullable=False)
    entry_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_pool_entries.id", ondelete="CASCADE"), nullable=False)
    dg_id: Mapped[int] = mapped_column(Integer, nullable=False)
    player_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    pick_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket_number: Mapped[int | None] = mapped_column(Integer)
    status_snapshot: Mapped[str | None] = mapped_column(String(30))
    position_snapshot: Mapped[int | None] = mapped_column(Integer)
    thru_snapshot: Mapped[int | None] = mapped_column(Integer)
    r1: Mapped[int | None] = mapped_column(Integer)
    r2: Mapped[int | None] = mapped_column(Integer)
    r3: Mapped[int | None] = mapped_column(Integer)
    r4: Mapped[int | None] = mapped_column(Integer)
    total_score_snapshot: Mapped[int | None] = mapped_column(Integer)
    made_cut_snapshot: Mapped[bool | None] = mapped_column(Boolean)
    counts_toward_total: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_dropped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_score: Mapped[int | None] = mapped_column(Integer)
    last_scored_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfPoolEntryScore(Base):
    __tablename__ = "golf_pool_entry_scores"
    __table_args__ = (
        Index("idx_golf_pool_entry_scores_pool_rank", "pool_id", "rank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_pools.id", ondelete="CASCADE"), nullable=False)
    entry_id: Mapped[int] = mapped_column(Integer, ForeignKey("golf_pool_entries.id", ondelete="CASCADE"), nullable=False, unique=True)
    aggregate_score: Mapped[int | None] = mapped_column(Integer)
    qualified_golfers_count: Mapped[int] = mapped_column(Integer, nullable=False)
    counted_golfers_count: Mapped[int] = mapped_column(Integer, nullable=False)
    qualification_status: Mapped[str] = mapped_column(String(30), nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    is_tied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scoring_json = Column(JSONB)
    last_scored_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GolfPoolScoreRun(Base):
    __tablename__ = "golf_pool_score_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("golf_pools.id", ondelete="CASCADE"))
    tournament_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("golf_tournaments.id", ondelete="CASCADE"))
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    entries_scored: Mapped[int] = mapped_column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
