"""HTTP surface for Scroll Down MLB.

Endpoints — consumer namespace per repo policy
(`tests/test_router_namespaces.py`):

  GET /api/v1/scroll-down-mlb/games/recent              — spoiler-safe feed
  GET /api/v1/scroll-down-mlb/games/{game_id}/deck      — pre-reveal deck
  GET /api/v1/scroll-down-mlb/games/{game_id}/reveal    — final-score reveal
  GET /api/v1/scroll-down-mlb/pressure/today            — arcade pack (yesterday's games)
  GET /api/v1/scroll-down-mlb/pressure/daily/{date}     — arcade pack for a specific date

Phase 5 wires the service to the real SDA database. The router itself
stays thin — orchestration lives in `service.py` (deck endpoints) and
`arcade_pack_service.py` (pressure endpoints).
"""

from __future__ import annotations

import datetime
import logging
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response, status
from fastapi.responses import JSONResponse

from app.db import AsyncSession, get_db
from app.utils.datetime_utils import today_et

from . import service
from .arcade_pack_service import (
    DailyPressurePack,
    NoPressurePackAvailable,
    build_daily_pressure_pack,
)
from .schemas import (
    ArcadeDailyPressurePackResponse,
    ArcadePressureMomentResponse,
    ArcadePressureTier,
    ScrollDownMlbDeckResponse,
    ScrollDownMlbRecentResponse,
    ScrollDownMlbRevealResponse,
)
from .validation import validate_no_final_score_leak

logger = logging.getLogger(__name__)

# Strict ISO 8601 calendar date — four-digit year, zero-padded month/day.
# `datetime.date.fromisoformat` accepts looser variants on Python 3.11+
# (basic-format, ordinal), but the arcade contract only wants extended
# YYYY-MM-DD so we gate on the regex before delegating to fromisoformat.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _if_none_match_hits(if_none_match: str, current_etag: str) -> bool:
    """RFC 7232-flavored match: split on commas, strip W/ prefix + quotes."""
    for candidate in if_none_match.split(","):
        token = candidate.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:]
        if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
            token = token[1:-1]
        if token == current_etag:
            return True
    return False

router = APIRouter(prefix="/api/v1/scroll-down-mlb", tags=["scroll-down-mlb"])


@router.get(
    "/games/recent",
    response_model=ScrollDownMlbRecentResponse,
    response_model_by_alias=True,
)
async def list_recent_games(
    session: AsyncSession = Depends(get_db),
) -> ScrollDownMlbRecentResponse:
    """Recent games for the catch-up feed.

    Spoiler-safe: no scores, no winners. The frontend's home grid renders
    matchups only.
    """
    games = await service.get_recent_games(session)
    return ScrollDownMlbRecentResponse(games=games)


@router.get(
    "/games/{game_id}/deck",
    response_model=ScrollDownMlbDeckResponse,
    response_model_by_alias=True,
)
async def get_game_deck(
    response: Response,
    game_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[0-9]+$"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    session: AsyncSession = Depends(get_db),
):
    """Spoiler-safe deck for the catch-up flow.

    Returns whichever deck (live provisional or official) is most current.
    The client uses `deckVersion` to detect updates without diffing cards.

    Supports conditional GETs: when the client sends `If-None-Match` with
    the previously seen `deckVersion`, the server short-circuits to 304
    using a lightweight metadata-only version check — avoiding both the
    payload load and the full build pipeline when nothing has changed.
    """
    if if_none_match is not None:
        current_etag = await service.compute_deck_etag(session, game_id)
        if current_etag is not None and _if_none_match_hits(
            if_none_match, current_etag
        ):
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers={"ETag": f'"{current_etag}"'},
            )
    deck = await service.get_game_deck(session, game_id)
    if deck is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deck available for this game yet.",
        )
    response.headers["ETag"] = f'"{deck.deck_version}"'
    return deck


@router.get(
    "/games/{game_id}/reveal",
    response_model=ScrollDownMlbRevealResponse,
    response_model_by_alias=True,
)
async def get_game_reveal(
    game_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[0-9]+$"),
    session: AsyncSession = Depends(get_db),
) -> ScrollDownMlbRevealResponse:
    """Final-score reveal — the ONLY endpoint allowed to leak the result.

    Returns 409 if the game has not yet produced a reveal payload (in
    progress, postponed, or upstream not ready).
    """
    reveal = await service.get_game_reveal(session, game_id)
    if reveal is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reveal not available yet for this game.",
        )
    return reveal


# ---------------------------------------------------------------------------
# Arcade — daily pressure pack
# ---------------------------------------------------------------------------


@router.get(
    "/pressure/today",
    response_model=ArcadeDailyPressurePackResponse,
    response_model_by_alias=True,
)
async def get_pressure_today(session: AsyncSession = Depends(get_db)):
    """Arcade pack for "today's" games — which in MLB-fan parlance means
    yesterday's slate (games that started last night ET and have a final
    pre-reveal deck persisted).

    Computed server-side from the ET calendar so a 10pm ET game on May 13
    is grouped with the May 13 slate, even though its UTC timestamp may
    have rolled into May 14.
    """
    target_date = today_et() - datetime.timedelta(days=1)
    return await _get_or_build_pack(target_date, session)


@router.get(
    "/pressure/daily/{date}",
    response_model=ArcadeDailyPressurePackResponse,
    response_model_by_alias=True,
)
async def get_pressure_daily(
    # `date` shadows ``datetime.date``; the module imports ``datetime`` (not
    # the name ``date``) so there is no collision in this function.
    date: str = Path(..., min_length=10, max_length=10),  # noqa: A002
    session: AsyncSession = Depends(get_db),
):
    """Arcade pack for an explicit MLB calendar date.

    Returns:
      * 422 if ``date`` is not a strict ISO 8601 ``YYYY-MM-DD`` string.
      * 400 if ``date`` is after yesterday — those games are still live or
        unplayed, so a pack does not exist yet.
      * 404 (with ``{detail, date}`` body) if no pack data exists for the
        requested date.
    """
    if not _ISO_DATE_RE.match(date):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid date format: {date!r}. Expected ISO 8601 YYYY-MM-DD "
                "with zero-padded month and day."
            ),
        )
    try:
        target_date = datetime.date.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date: {date!r} is not a real calendar date.",
        ) from exc

    yesterday = today_et() - datetime.timedelta(days=1)
    if target_date > yesterday:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No games have been played yet for {target_date.isoformat()}",
        )

    return await _get_or_build_pack(target_date, session)


async def _get_or_build_pack(
    target_date: datetime.date, session: AsyncSession
) -> ArcadeDailyPressurePackResponse | JSONResponse:
    """Build the pack or return a structured 404 if none is available.

    The 404 body is intentionally flat (``{detail, date}``) rather than the
    nested ``{detail: {...}}`` shape FastAPI produces when ``HTTPException``
    is given a dict ``detail`` — the arcade client reads ``date`` at the
    top level to render a meaningful "no games yet" message.
    """
    try:
        pack = await build_daily_pressure_pack(target_date, session)
    except NoPressurePackAvailable:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": f"No pressure pack available for {target_date.isoformat()}",
                "date": target_date.isoformat(),
            },
        )
    return _pack_to_response(pack)


def _pack_to_response(pack: DailyPressurePack) -> ArcadeDailyPressurePackResponse:
    # Defense-in-depth: card_payload is `dict[str, Any]` in the response
    # schema, so the typed wire contract that protects the deck endpoint
    # (`ScoreSituation` only on `situationBefore`) doesn't apply here. The
    # spoiler-policy filter on the DB query is the primary safety; this
    # second check fires only if a future bug ever persisted a leaking
    # payload under the pre-reveal policy. Fail-closed with 500 rather
    # than serve a leaking pack — see security-report.md "Changes made
    # this pass (Pass 3)" + finding S6.
    for moment in pack.moments:
        findings = validate_no_final_score_leak(moment.card_payload)
        if findings:
            logger.error(
                "arcade_pack_final_score_leak_detected",
                extra={
                    "pack_date": pack.pack_date.isoformat(),
                    "game_id": moment.game_id,
                    "play_index": moment.play_index,
                    "finding_codes": [f.code for f in findings],
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Pressure pack unavailable.",
            )
    return ArcadeDailyPressurePackResponse(
        date=pack.pack_date,
        moments=[
            ArcadePressureMomentResponse(
                game_id=str(moment.game_id),
                play_index=moment.play_index,
                rank=moment.rank,
                difficulty=moment.difficulty,
                tier=ArcadePressureTier(moment.tier),
                card_payload=moment.card_payload,
            )
            for moment in pack.moments
        ],
    )
