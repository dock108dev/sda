"""Persistence shell for Scroll Down MLB decks.

Reads and writes the `scroll_down_mlb_decks` table. Phase 2 implements only
the function signatures and a minimal upsert / latest-fetch path so the
service layer can be wired without further DB plumbing in Phase 3.

The stored row is the full deck DTO as JSONB so /deck can serve it without
re-running the builder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scroll_down_mlb import ScrollDownMlbDeck

from .schemas import (
    ScrollDownMlbDeckResponse,
    SpoilerPolicy,
    ValidationWarning,
)


async def fetch_latest_deck(
    session: AsyncSession,
    game_id: int,
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.pre_reveal,
) -> ScrollDownMlbDeckResponse | None:
    """Return the most recently generated deck for `game_id`, or None."""
    stmt = (
        select(ScrollDownMlbDeck)
        .where(
            ScrollDownMlbDeck.game_id == game_id,
            ScrollDownMlbDeck.spoiler_policy == spoiler_policy.value,
        )
        .order_by(ScrollDownMlbDeck.generated_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return ScrollDownMlbDeckResponse.model_validate(row.payload_json)


async def fetch_official_deck(
    session: AsyncSession, game_id: int
) -> ScrollDownMlbDeckResponse | None:
    """Return the canonical official deck for `game_id`, or None."""
    stmt = (
        select(ScrollDownMlbDeck)
        .where(
            ScrollDownMlbDeck.game_id == game_id,
            ScrollDownMlbDeck.spoiler_policy == SpoilerPolicy.pre_reveal.value,
            ScrollDownMlbDeck.is_final.is_(True),
        )
        .order_by(ScrollDownMlbDeck.generated_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return ScrollDownMlbDeckResponse.model_validate(row.payload_json)


async def upsert_deck(
    session: AsyncSession,
    *,
    game_id: int,
    deck: ScrollDownMlbDeckResponse,
    warnings: list[ValidationWarning] | None = None,
    errors: list[ValidationWarning] | None = None,
    planner_report: dict[str, Any] | None = None,
    source_hash: str | None = None,
    generator_label: str | None = None,
) -> None:
    """Insert or update the deck row for (game_id, deck_version, spoiler_policy).

    Uses Postgres ON CONFLICT so a regenerated deck overwrites cleanly. The
    full deck DTO is stored as JSONB.
    """
    payload = deck.model_dump(mode="json", by_alias=True)
    stmt = (
        pg_insert(ScrollDownMlbDeck)
        .values(
            game_id=game_id,
            deck_version=deck.deck_version,
            spoiler_policy=deck.spoiler_policy.value,
            is_final=deck.is_final,
            payload_json=payload,
            planner_report_json=planner_report,
            validation_warnings_json=[w.model_dump(mode="json", by_alias=True) for w in (warnings or [])],
            validation_errors_json=[e.model_dump(mode="json", by_alias=True) for e in (errors or [])],
            source_hash=source_hash,
            generated_at=datetime.now(UTC),
            card_count=len(deck.cards),
            generator_label=generator_label,
        )
        .on_conflict_do_update(
            index_elements=["game_id", "deck_version", "spoiler_policy"],
            set_={
                "is_final": deck.is_final,
                "payload_json": payload,
                "planner_report_json": planner_report,
                "validation_warnings_json": [
                    w.model_dump(mode="json", by_alias=True) for w in (warnings or [])
                ],
                "validation_errors_json": [
                    e.model_dump(mode="json", by_alias=True) for e in (errors or [])
                ],
                "source_hash": source_hash,
                "generated_at": datetime.now(UTC),
                # ORM-level `onupdate` doesn't fire for ON CONFLICT DO UPDATE,
                # so refresh updated_at explicitly on regeneration.
                "updated_at": datetime.now(UTC),
                "card_count": len(deck.cards),
                "generator_label": generator_label,
            },
        )
    )
    await session.execute(stmt)
