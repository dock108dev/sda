"""SQLAlchemy models for Scroll Down MLB deck persistence.

The deck table stores generated decks (live and official) keyed by
(game_id, deck_version, spoiler_policy). Payloads are JSONB so the schema
can evolve without churn while the deck shape stabilizes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
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


class ScrollDownMlbDeck(Base):
    """A generated Scroll Down deck for one MLB game.

    There can be many rows per game: one per `deck_version` per
    `spoiler_policy`. Live polling produces a sequence of `pre_reveal`
    versions. The first `is_final=True` row with `spoiler_policy=pre_reveal`
    is treated as the canonical official deck.
    """

    __tablename__ = "scroll_down_mlb_decks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    game_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deck_version: Mapped[str] = mapped_column(String(64), nullable=False)
    spoiler_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Full deck DTO as built. Stored as JSONB so /deck can serve it directly
    # without re-running the builder.
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Planner reasoning + validation findings. Read by QA / admin tools, not
    # by the public deck endpoint.
    planner_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    validation_warnings_json: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    validation_errors_json: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    # Hash of the upstream input the deck was built from. Lets the service
    # short-circuit re-generation when nothing has changed.
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Wall clock when the builder finished. Distinct from `created_at`
    # because a deck row may be re-stored after re-generation.
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Soft cardinality summary — answer "did anything change?" without
    # parsing payload_json on every list query.
    card_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Free-text generator label ("backend-py-v0", "live-poll-v1" etc.) for
    # debugging across deploys.
    generator_label: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "game_id",
            "deck_version",
            "spoiler_policy",
            name="uq_scroll_down_mlb_decks_game_version_policy",
        ),
        Index("ix_scroll_down_mlb_decks_game_id", "game_id"),
        Index(
            "ix_scroll_down_mlb_decks_game_id_generated_at",
            "game_id",
            "generated_at",
        ),
    )


class ArcadeDailyPressurePack(Base):
    """A daily snapshot of the arcade pressure pack.

    One row per ``pack_date``; ``pack_version`` increments when the same
    date's pack is regenerated. ``is_final`` flips to true once the day's
    real-world signals are settled and the pack will not be regenerated.
    """

    __tablename__ = "arcade_daily_pressure_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    pack_date: Mapped[date] = mapped_column(Date, nullable=False)
    pack_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_arcade_daily_pressure_packs_pack_date",
            "pack_date",
            unique=True,
        ),
    )
