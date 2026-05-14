"""Cross-game daily pressure moment selection.

Reads persisted ``ScrollDownMlbDeck`` rows for one MLB calendar date,
extracts the per-play cards from each deck's payload, scores them with
:mod:`arcade_scoring`, and returns the top-N (default 5) by difficulty.

The function is date-agnostic — the caller passes an explicit ``date``
argument so the same code is exercised by the ``/pressure/today``
endpoint (which supplies yesterday's date in the MLB schedule timezone)
and by tests (which supply any date). Nothing in this module knows about
"today" or "yesterday".

Selection contract:

* Zero deck rows for the date → ``NoPressurePackAvailable`` is raised.
  An empty moments list is not a valid arcade experience; the endpoint
  layer turns the exception into a structured HTTP 404.
* Fewer than ``pack_size`` candidates (short slate, early season) →
  the pack carries however many exist, never zero — if play candidates
  survive the dedup pass, at least one moment is returned.
* Duplicate ``(game_id, play_index)`` pairs across multiple deck rows
  for the same game (e.g. multiple ``deck_version`` rows persisted) are
  collapsed before scoring.

Pure helpers expose the deduplication, candidate extraction, and per-
candidate scoring so they can be exercised without a database.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scroll_down_mlb import ScrollDownMlbDeck
from app.db.sports import SportsGame, SportsLeague

from .arcade_scoring import PressureTier, difficulty_score, pressure_tier
from .schemas import SpoilerPolicy

__all__ = [
    "DEFAULT_PACK_SIZE",
    "DailyPressurePack",
    "NoPressurePackAvailable",
    "PressureMoment",
    "build_daily_pressure_pack",
]

DEFAULT_PACK_SIZE = 5
_LATE_INNING_THRESHOLD = 7
_LATE_LEVERAGE_MARGIN = 2


class NoPressurePackAvailable(Exception):
    """Raised when no completed decks exist for the requested date.

    The endpoint layer catches this and returns a structured 404 that
    carries the date back to the client (see ``/pressure/today``).
    """

    def __init__(self, date: datetime.date) -> None:
        super().__init__(f"No pressure pack available for {date.isoformat()}")
        self.date = date


@dataclass(frozen=True)
class PressureMoment:
    """One selected moment in the daily pressure pack.

    ``card_payload`` is the spoiler-safe wire dict the deck builder
    persisted to ``payload_json.cards[*]`` — downstream callers use it to
    assemble situation / matchup / recap for the arcade contract without
    re-querying upstream data.
    """

    game_id: int
    play_index: int
    rank: int
    difficulty: int
    tier: PressureTier
    card_payload: dict[str, Any]


@dataclass(frozen=True)
class DailyPressurePack:
    """A daily slate of pressure moments. Always non-empty by construction."""

    pack_date: datetime.date
    moments: tuple[PressureMoment, ...]


async def build_daily_pressure_pack(
    date: datetime.date,
    session: AsyncSession,
    *,
    pack_size: int = DEFAULT_PACK_SIZE,
) -> DailyPressurePack:
    """Select up to ``pack_size`` highest-leverage moments for ``date``.

    Caller supplies the date — this function does not compute 'yesterday'.
    Raises :class:`NoPressurePackAvailable` when no decks (or no scorable
    plays) exist for the date.
    """
    decks = await _fetch_decks_for_date(session, date)
    if not decks:
        raise NoPressurePackAvailable(date)

    candidates = collect_candidates(decks)
    if not candidates:
        raise NoPressurePackAvailable(date)

    scored = [(score_candidate(c), c) for c in candidates]
    # Highest difficulty first; (game_id, play_index) break ties deterministically.
    scored.sort(key=lambda pair: (-pair[0], pair[1].game_id, pair[1].play_index))

    size = max(1, pack_size)
    top = scored[:size]
    moments = tuple(
        PressureMoment(
            game_id=cand.game_id,
            play_index=cand.play_index,
            rank=rank,
            difficulty=score,
            tier=pressure_tier(score),
            card_payload=cand.card,
        )
        for rank, (score, cand) in enumerate(top, start=1)
    )
    return DailyPressurePack(pack_date=date, moments=moments)


# ---------------------------------------------------------------------------
# Pure helpers — exported for direct unit testing without a database.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    game_id: int
    play_index: int
    card: dict[str, Any]


def collect_candidates(decks: list[ScrollDownMlbDeck]) -> list[_Candidate]:
    """Flatten decks → play candidates, deduped by ``(game_id, play_index)``.

    Cards whose ``type`` is not ``"play"`` (scene / rhythm / final-setup)
    and play cards without a parseable ``play.playId`` are skipped — they
    have no plate-appearance identity to score.
    """
    seen: set[tuple[int, int]] = set()
    out: list[_Candidate] = []
    for deck in decks:
        game_id = deck.game_id
        payload = deck.payload_json or {}
        for card in payload.get("cards", []) or []:
            if not isinstance(card, dict):
                continue
            if card.get("type") != "play":
                continue
            play = card.get("play")
            if not isinstance(play, dict):
                continue
            play_index = _coerce_int(play.get("playId"))
            if play_index is None:
                continue
            key = (game_id, play_index)
            if key in seen:
                continue
            seen.add(key)
            out.append(_Candidate(game_id=game_id, play_index=play_index, card=card))
    return out


def score_candidate(candidate: _Candidate) -> int:
    """Run :func:`arcade_scoring.difficulty_score` against a wire card.

    Derives ``is_tying_play`` / ``is_lead_change_play`` from the public
    ``scoreBefore`` + ``scoreChange`` fields rather than the internal
    ``TimelineEntry`` (which is not on the persisted deck). ``is_late_leverage``
    is rederived from ``inning`` + score margin so the service is fully
    decoupled from upstream pipeline state.
    """
    card = candidate.card
    play = card.get("play") or {}

    inning = _coerce_int(card.get("inning")) or 1
    half_raw = card.get("half")
    half = half_raw if isinstance(half_raw, str) else "top"
    outs_before = _coerce_int(play.get("outsBefore")) or 0

    bases_src = play.get("baseStateBefore") or {}
    base_state_before = {
        "first": bool(bases_src.get("first")),
        "second": bool(bases_src.get("second")),
        "third": bool(bases_src.get("third")),
    }

    score_before = play.get("scoreBefore") or {}
    home_before = _coerce_int(score_before.get("home")) or 0
    away_before = _coerce_int(score_before.get("away")) or 0

    score_change = play.get("scoreChange") or {}
    home_delta = _coerce_int(score_change.get("home")) or 0
    away_delta = _coerce_int(score_change.get("away")) or 0
    home_after = home_before + home_delta
    away_after = away_before + away_delta

    prev_lead = home_before - away_before
    new_lead = home_after - away_after
    is_tying = prev_lead != 0 and new_lead == 0
    is_lead_change = (
        prev_lead != 0
        and new_lead != 0
        and (prev_lead > 0) != (new_lead > 0)
    )
    margin = abs(prev_lead)
    is_late_leverage = (
        inning >= _LATE_INNING_THRESHOLD and margin <= _LATE_LEVERAGE_MARGIN
    )

    leverage_tier = card.get("leverageTier")
    if not isinstance(leverage_tier, int):
        leverage_tier = None

    return difficulty_score(
        inning=inning,
        half=half,
        outs_before=outs_before,
        base_state_before=base_state_before,
        score_margin=margin,
        leverage_tier=leverage_tier,
        is_tying_play=is_tying,
        is_lead_change_play=is_lead_change,
        is_late_leverage=is_late_leverage,
    )


# ---------------------------------------------------------------------------
# Private DB query + coercion
# ---------------------------------------------------------------------------


async def _fetch_decks_for_date(
    session: AsyncSession, target_date: datetime.date
) -> list[ScrollDownMlbDeck]:
    """Return final pre-reveal MLB decks for games played on ``target_date``.

    Filters on ``SportsGame.local_game_date`` (the ET calendar date the
    game is officially scheduled for) so a late East-Coast game whose UTC
    timestamp rolled to the next day still groups with its real-world
    date.
    """
    stmt = (
        select(ScrollDownMlbDeck)
        .join(SportsGame, SportsGame.id == ScrollDownMlbDeck.game_id)
        .join(SportsLeague, SportsLeague.id == SportsGame.league_id)
        .where(
            SportsGame.local_game_date == target_date,
            SportsLeague.code.ilike("mlb"),
            ScrollDownMlbDeck.is_final.is_(True),
            ScrollDownMlbDeck.spoiler_policy == SpoilerPolicy.pre_reveal.value,
        )
        .order_by(
            ScrollDownMlbDeck.game_id,
            ScrollDownMlbDeck.generated_at.desc(),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        # bool is a subclass of int in Python — guard explicitly so a
        # stray boolean play_index doesn't slip through as 0 or 1.
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None
