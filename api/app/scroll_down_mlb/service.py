"""Orchestration for Scroll Down MLB.

The router calls into here. Phase 3 wires the full pipeline:

    upstream payload
    → compute_timeline + compute_pitcher_timeline (game_state)
    → select_plays + sample_tier_2 (deck_builder)
    → to_play_card                 (deck_builder)
    → result_chip + narrative      (per-card decoration)
    → leverage tier                (visual_mapper)
    → plan_deck                    (rhythm_planner)
    → validate                     (validation)
    → apply_validation_policy      (this module)
    → built-deck → spoiler-safe DTO (built_to_dto)
    → persist                      (persistence)

The `build_deck_from_upstream` entry is the parity surface — fixture
tests call it directly with a captured upstream payload and compare the
result to the TS snapshot.

`get_game_deck` / `get_game_reveal` / `get_recent_games` remain the
router entry points. They will be wired to a real upstream in a follow-up;
in this phase they fall back to the stub when no payload source is
configured.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.scroll_down_mlb import ScrollDownMlbDeck
from app.db.sports import GameStatus, SportsGame, SportsLeague

from . import persistence
from .data_source import load_game_payload
from .deck_builder import (
    build_scene_setter,
    select_plays,
    to_play_card,
)
from .game_state import (
    compute_pitcher_timeline,
    compute_timeline,
    summarize_half_innings,
)
from .internal_types import BuiltPlayCard, RunnerAdvance
from .narrative import narrative_for_card
from .result_labels import result_chip_label
from .rhythm_planner import DeckItem, plan_deck_with_report
from .schemas import (
    BaseState,
    DeckCardType,
    GenerationOutcome,
    GenerationPolicy,
    PlannerNote,
    PlayPayload,
    RunnerMovement,
    ScoreState,
    ScrollDownMlbDeckCard,
    ScrollDownMlbDeckResponse,
    ScrollDownMlbRecentGame,
    ScrollDownMlbRevealResponse,
    TeamSummary,
    ValidationSeverity,
    ValidationWarning,
    VisualPayload,
)
from .schemas import (
    PlannerReport as DtoPlannerReport,
)
from .validation import (
    validate_no_duplicate_play_ids,
    validate_no_final_score_leak,
    validate_play_card,
)
from .visual_mapper import classify_runner_style, compute_leverage_tier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation severity policy
# ---------------------------------------------------------------------------


def apply_validation_policy(
    findings: Iterable[ValidationWarning], policy: GenerationPolicy
) -> tuple[list[ValidationWarning], list[ValidationWarning], bool]:
    """Split findings into (warnings, errors, blocked) per policy."""
    warnings: list[ValidationWarning] = []
    errors: list[ValidationWarning] = []
    for finding in findings:
        if finding.severity is ValidationSeverity.error:
            if policy is GenerationPolicy.official:
                errors.append(finding)
            else:
                warnings.append(
                    finding.model_copy(update={"severity": ValidationSeverity.warning})
                )
        else:
            warnings.append(finding)
    blocked = policy is GenerationPolicy.official and bool(errors)
    return warnings, errors, blocked


# ---------------------------------------------------------------------------
# Built-deck → spoiler-safe DTO
# ---------------------------------------------------------------------------


def _base_state_dto(state: dict[str, bool]) -> BaseState:
    return BaseState(
        first=bool(state.get("first")),
        second=bool(state.get("second")),
        third=bool(state.get("third")),
    )


def _runner_movements_dto(
    advances: list[RunnerAdvance],
    event_type: str | None,
    runner_names_before: dict[str, str],
    batter_name: str | None,
) -> list[RunnerMovement]:
    out: list[RunnerMovement] = []
    for adv in advances:
        # Resolve the runner's display name.
        if adv.from_base in ("first", "second", "third"):
            name = runner_names_before.get(adv.from_base) or "Runner"
        elif adv.from_base == "home":
            name = batter_name or "Batter"
        else:
            name = "Runner"
        style = classify_runner_style(adv, event_type)
        out.append(
            RunnerMovement(
                runner=name,
                from_base=adv.from_base,
                to_base=adv.to,
                style=(
                    "score"
                    if style == "score"
                    else "out"
                    if style in ("forced_out", "tagged_out", "in_place_out", "double_play")
                    else "advance"
                ),
                out_at=adv.out_at,
            )
        )
    return out


def _decorate(card: BuiltPlayCard) -> None:
    """Compute per-card derived fields (narrative, chip label, leverage)."""
    label = result_chip_label(card)
    card.chip_primary = label.primary
    card.chip_secondary = label.secondary
    card.narrative = narrative_for_card(card)
    bases = card.base_state_before
    bases_loaded = bool(
        bases.get("first") and bases.get("second") and bases.get("third")
    )
    card.leverage_tier = compute_leverage_tier(
        inning=card.inning,
        score_before_home=card.score_before_home,
        score_before_away=card.score_before_away,
        score_after_home=card.score_after_home,
        score_after_away=card.score_after_away,
        outs_before=card.outs_before,
        bases_loaded_before=bases_loaded,
    )


def _play_card_dto(card: BuiltPlayCard) -> ScrollDownMlbDeckCard:
    """Convert a BuiltPlayCard to its spoiler-safe DTO. Drops score_after."""
    runs_scored = (
        (card.score_after_home - card.score_before_home)
        + (card.score_after_away - card.score_before_away)
    )
    # Filter runner names to the spoiler-safe per-base map (no batter).
    def _names(src: dict[str, str]) -> dict[str, str]:
        return {
            k: v
            for k, v in src.items()
            if k in ("first", "second", "third") and isinstance(v, str) and v
        }

    play = PlayPayload(
        play_id=str(card.play_index),
        event_type=card.event_type,
        label=card.chip_primary,
        sub_label=card.chip_secondary,
        description=card.narrative or card.description,
        batter_name=card.batter_name,
        pitcher_name=card.pitcher_name,
        balls_before=card.balls_before,
        strikes_before=card.strikes_before,
        outs_before=card.outs_before,
        outs_after=card.outs_after,
        base_state_before=_base_state_dto(card.base_state_before),
        base_state_after=_base_state_dto(card.base_state_after),
        runner_names_before=_names(card.runner_names_before),
        runner_names_after=_names(card.runner_names_after),
        score_before=ScoreState(
            home=card.score_before_home, away=card.score_before_away
        ),
        runs_scored_on_play=max(0, runs_scored),
    )
    visual = VisualPayload(
        trajectory=card.ball_path if card.ball_path not in (None, "none") else None,
        runner_movements=_runner_movements_dto(
            card.advances,
            card.event_type,
            card.runner_names_before,
            card.batter_name,
        ),
        intensity=card.visual_intensity if card.visual_intensity in ("low", "medium", "high") else None,
        animation_profile=card.animation_profile,
    )
    return ScrollDownMlbDeckCard(
        id=f"{card.game_id}-{card.play_index}",
        type=DeckCardType.play,
        sort_order=card.sort_order,
        inning=card.inning,
        half=card.inning_half,
        title=card.inning_label,
        description=card.narrative or card.description,
        play=play,
        visual=visual,
        leverage_tier=card.leverage_tier,
    )


def _scene_card_dto(scene: dict[str, Any], sort_order: int) -> ScrollDownMlbDeckCard:
    return ScrollDownMlbDeckCard(
        id=str(scene.get("cardId", "scene")),
        type=DeckCardType.scene,
        sort_order=sort_order,
        title="First pitch",
        description=(
            f"{scene.get('awayTeam', 'Away')} at {scene.get('homeTeam', 'Home')}"
        ),
    )


def _rhythm_card_dto(card: dict[str, Any], sort_order: int) -> ScrollDownMlbDeckCard:
    kind = card.get("kind", "rhythm")
    dto_kind = DeckCardType.final_setup if kind == "final-setup" else DeckCardType.rhythm
    description = card.get("subtitle") or card.get("label", "")
    to_inning = card.get("toInning")
    to_half = card.get("toHalf")
    return ScrollDownMlbDeckCard(
        id=str(card.get("cardId", f"rhythm-{sort_order}")),
        type=dto_kind,
        sort_order=sort_order,
        inning=to_inning if isinstance(to_inning, int) else None,
        half=to_half if to_half in ("top", "bottom") else None,
        title=card.get("label"),
        description=description,
    )


def built_deck_to_dto(
    *,
    game_id: int,
    deck: list[DeckItem],
    planner_report_entries: list[Any],
    validation_warnings: list[ValidationWarning],
    is_final: bool,
    deck_version: str,
    home_team: TeamSummary | None = None,
    away_team: TeamSummary | None = None,
    last_play_index: int | None = None,
    first_pitch: str | None = None,
    venue: str | None = None,
    home_probable_pitcher: str | None = None,
    away_probable_pitcher: str | None = None,
) -> ScrollDownMlbDeckResponse:
    """Final boundary: convert the built deck to the spoiler-safe DTO.

    Strips post-play score, ensures camelCase wire serialization, runs the
    final-score-leak detector, and assembles the response.
    """
    cards: list[ScrollDownMlbDeckCard] = []
    for item in deck:
        if isinstance(item, BuiltPlayCard):
            cards.append(_play_card_dto(item))
        elif isinstance(item, dict):
            kind = item.get("kind")
            if kind == "scene-setter":
                cards.append(_scene_card_dto(item, item.get("index", len(cards))))
            else:
                cards.append(_rhythm_card_dto(item, item.get("index", len(cards))))

    planner_report = DtoPlannerReport(
        rhythm=[
            PlannerNote(
                card_id=e.card_id,
                kind=e.kind,
                reason=e.reason,
                after_play_index=e.after_play_index,
                before_play_index=e.before_play_index,
            )
            for e in planner_report_entries
        ]
    )
    response = ScrollDownMlbDeckResponse(
        game_id=str(game_id),
        deck_version=deck_version,
        generated_at=datetime.now(UTC),
        is_final=is_final,
        home_team=home_team,
        away_team=away_team,
        last_play_index=last_play_index,
        first_pitch=first_pitch,
        venue=venue,
        home_probable_pitcher=home_probable_pitcher,
        away_probable_pitcher=away_probable_pitcher,
        cards=cards,
        planner_report=planner_report,
        validation_warnings=validation_warnings,
    )

    # Final spoiler-safety guard: scan the serialized payload for any
    # forbidden keys and surface as a hard validation finding if present.
    leak_findings = validate_no_final_score_leak(
        response.model_dump(mode="json", by_alias=True)
    )
    if leak_findings:
        # Append to the warnings list — the official policy gate will block.
        response.validation_warnings.extend(leak_findings)

    return response


# ---------------------------------------------------------------------------
# Build a deck from an upstream payload (used by parity tests)
# ---------------------------------------------------------------------------


def _source_hash(payload: dict[str, Any]) -> str:
    """Stable signature of the inputs a deck was built from.

    Live polling uses this to decide whether the deck has actually
    changed:

      - gameId      (identity)
      - status      (live → final transitions force a new version)
      - playCount   (any new play forces a new version)
      - lastPlayIndex (covers re-orderings and back-fills)
      - homeScore / awayScore (covers backend score corrections that
        don't necessarily add a new play row)
      - lastPlayAt / lastIngestedAt (covers updates that fix data on
        existing plays — description corrections, runner attribution)

    These fields together give a deterministic-but-sensitive signature.
    Hash is truncated to 16 hex chars; collision risk is negligible for
    the keyspace (one game's lifetime).
    """
    game = payload.get("game") or {}
    plays = payload.get("plays") or []
    plays_sorted = sorted(plays, key=lambda p: p.get("playIndex", 0))
    last_idx = plays_sorted[-1].get("playIndex") if plays_sorted else None
    digest_input = {
        "gameId": game.get("id"),
        "status": game.get("status"),
        "playCount": len(plays),
        "lastPlayIndex": last_idx,
        "homeScore": game.get("homeScore"),
        "awayScore": game.get("awayScore"),
        "lastPlayAt": game.get("lastPlayAt"),
        "lastIngestedAt": game.get("lastIngestedAt"),
    }
    digest = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True).encode("utf-8")
    )
    return digest.hexdigest()[:16]


def build_deck_from_upstream(
    payload: dict[str, Any],
    *,
    policy: GenerationPolicy = GenerationPolicy.official,
    since_play_index: int | None = None,
) -> GenerationOutcome:
    """Build a Scroll Down MLB deck from an upstream game-detail payload.

    The payload shape mirrors the existing Next.js BFF: `{game, plays,
    mlbPitchers}`. For live polling, pass `since_play_index` to limit
    selected plays to those after the last one the client saw.
    """
    game = payload.get("game") or {}
    plays = list(payload.get("plays") or [])
    pitchers = payload.get("mlbPitchers")
    home_abbr = game.get("homeTeamAbbr")
    away_abbr = game.get("awayTeamAbbr")
    home_team = game.get("homeTeam", "Home")
    away_team = game.get("awayTeam", "Away")
    game_id = int(game.get("id") or 0)
    is_final = bool(game.get("isFinal")) or game.get("status") in (
        "final",
        "completed",
        "recap_ready",
        "archived",
    )

    # 1. Reconstruct game state across every play.
    timeline = compute_timeline(plays, home_abbr)
    pitcher_timeline = compute_pitcher_timeline(
        plays, pitchers, home_team, away_team, home_abbr
    )

    # 2. Select plays.
    selected_ids, _reasons = select_plays(plays, timeline, game_id)

    # 3. Filter by `since` and sort.
    threshold = since_play_index if since_play_index is not None else -1
    selected_plays = sorted(
        [p for p in plays if int(p.get("playIndex", 0)) in selected_ids
         and int(p.get("playIndex", 0)) > threshold],
        key=lambda p: int(p.get("playIndex", 0)),
    )

    # 4. Assemble play cards.
    home_pp = game.get("homeProbablePitcher")
    away_pp = game.get("awayProbablePitcher")
    play_cards: list[BuiltPlayCard] = []
    for play in selected_plays:
        pid = int(play.get("playIndex", 0))
        frame = timeline.get(pid)
        if not frame:
            continue
        card = to_play_card(
            game_id=game_id,
            sort_order=0,  # set by planner
            play=play,
            frame=frame,
            home_probable_pitcher=home_pp,
            away_probable_pitcher=away_pp,
            pitcher_of_record=pitcher_timeline.get(pid),
        )
        _decorate(card)
        play_cards.append(card)

    # 5. Plan rhythm.
    half_meta = summarize_half_innings(timeline.values())
    venue = game.get("venueName") or game.get("venue") or game.get("location")
    scene = (
        build_scene_setter(
            game_id=game_id,
            home_team=home_team,
            away_team=away_team,
            home_team_abbr=home_abbr,
            away_team_abbr=away_abbr,
            game_date=game.get("gameDate", ""),
            home_probable_pitcher=home_pp,
            away_probable_pitcher=away_pp,
            venue=venue,
        )
        if since_play_index is None
        else None
    )
    deck, planner_report = plan_deck_with_report(
        scene=scene,
        play_cards=play_cards,
        half_inning_meta=half_meta,
        home_team_abbr=home_abbr or "HME",
        away_team_abbr=away_abbr or "AWY",
    )

    # 6. Validate.
    findings: list[ValidationWarning] = []
    for card in play_cards:
        findings.extend(validate_play_card(card))
    findings.extend(validate_no_duplicate_play_ids([c.play_index for c in play_cards]))

    warnings, errors, blocked = apply_validation_policy(findings, policy)

    deck_version = (
        f"official-{_source_hash(payload)}"
        if policy is GenerationPolicy.official
        else f"live-{_source_hash(payload)}"
    )

    if blocked:
        return GenerationOutcome(
            policy=policy,
            deck=None,
            warnings=warnings,
            errors=errors,
            blocked=True,
        )

    last_play_index = max(
        (int(p.get("playIndex", 0)) for p in plays), default=None
    )
    home_team_dto = TeamSummary(
        id=str(game.get("homeTeamId") or home_abbr or "home"),
        abbreviation=home_abbr or "HME",
        display_name=home_team,
        color_light=game.get("homeTeamColorLight"),
        color_dark=game.get("homeTeamColorDark"),
    )
    away_team_dto = TeamSummary(
        id=str(game.get("awayTeamId") or away_abbr or "away"),
        abbreviation=away_abbr or "AWY",
        display_name=away_team,
        color_light=game.get("awayTeamColorLight"),
        color_dark=game.get("awayTeamColorDark"),
    )

    response = built_deck_to_dto(
        game_id=game_id,
        deck=deck,
        planner_report_entries=planner_report.rhythm,
        validation_warnings=warnings,
        is_final=is_final,
        deck_version=deck_version,
        home_team=home_team_dto,
        away_team=away_team_dto,
        last_play_index=last_play_index,
        first_pitch=game.get("gameDate"),
        venue=venue,
        home_probable_pitcher=home_pp,
        away_probable_pitcher=away_pp,
    )
    return GenerationOutcome(
        policy=policy,
        deck=response,
        warnings=warnings,
        errors=errors,
        blocked=False,
    )


# ---------------------------------------------------------------------------
# Public router entry points
# ---------------------------------------------------------------------------


_RECENT_WINDOW_HOURS = 48


async def get_recent_games(
    session: AsyncSession, *, now: datetime | None = None
) -> list[ScrollDownMlbRecentGame]:
    """Spoiler-safe recent-games feed.

    Returns MLB games whose first pitch falls within the last
    `_RECENT_WINDOW_HOURS` plus any later same-day games. Joined against
    the deck table for `hasDeck` / `deckVersion` so the home grid can
    show whether catch-up is ready without a second query.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(
        hours=_RECENT_WINDOW_HOURS
    )

    # Subquery: latest deck row per game.
    deck_subq = (
        select(
            ScrollDownMlbDeck.game_id.label("game_id"),
            func.max(ScrollDownMlbDeck.generated_at).label("latest_generated"),
        )
        .group_by(ScrollDownMlbDeck.game_id)
        .subquery()
    )

    stmt = (
        select(SportsGame, ScrollDownMlbDeck)
        .join(SportsLeague, SportsLeague.id == SportsGame.league_id)
        .options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
        )
        .join(
            deck_subq,
            deck_subq.c.game_id == SportsGame.id,
            isouter=True,
        )
        .join(
            ScrollDownMlbDeck,
            and_(
                ScrollDownMlbDeck.game_id == deck_subq.c.game_id,
                ScrollDownMlbDeck.generated_at == deck_subq.c.latest_generated,
            ),
            isouter=True,
        )
        .where(
            func.lower(SportsLeague.code) == "mlb",
            SportsGame.game_date >= cutoff,
        )
        .order_by(desc(SportsGame.game_date))
        .limit(50)
    )

    result = await session.execute(stmt)
    rows = result.all()

    games: list[ScrollDownMlbRecentGame] = []
    for game, deck_row in rows:
        is_final = GameStatus.is_final_or_post_final_status(game.status)
        is_pregame = (game.status or "").lower() in ("scheduled", "pregame")
        home = game.home_team
        away = game.away_team
        games.append(
            ScrollDownMlbRecentGame(
                game_id=str(game.id),
                game_date=(game.local_game_date if game.local_game_date else None),
                status=game.status,
                status_type=(
                    "final" if is_final else "pregame" if is_pregame else "live"
                ),
                away_team=TeamSummary(
                    id=str(away.id) if away else "away",
                    abbreviation=(away.abbreviation if away else "AWY") or "AWY",
                    display_name=away.name if away else "Away",
                    color_light=(away.color_light_hex if away else None),
                    color_dark=(away.color_dark_hex if away else None),
                ),
                home_team=TeamSummary(
                    id=str(home.id) if home else "home",
                    abbreviation=(home.abbreviation if home else "HME") or "HME",
                    display_name=home.name if home else "Home",
                    color_light=(home.color_light_hex if home else None),
                    color_dark=(home.color_dark_hex if home else None),
                ),
                venue_name=game.venue,
                start_time=game.game_date,
                has_deck=deck_row is not None,
                deck_version=deck_row.deck_version if deck_row is not None else None,
                is_final=is_final,
            )
        )
    return games


async def get_game_deck(
    session: AsyncSession, game_id: str
) -> ScrollDownMlbDeckResponse | None:
    """Return the (live or official) deck for `game_id`.

    Behavior:

      - Game not found / not MLB                  → None (router → 404)
      - Game scheduled / pregame                  → None (router → 404 or
        409 depending on the route's contract; current router → 404)
      - Game live: build fresh from current data, return live deck
      - Game final: serve persisted official deck if present; otherwise
        build, validate, persist (freeze), return.
    """
    try:
        gid = int(game_id)
    except (TypeError, ValueError):
        return None

    payload = await load_game_payload(session, gid)
    if payload is None:
        logger.info(
            "scroll_down_mlb.deck.not_found", extra={"game_id": gid}
        )
        return None

    game = payload.get("game") or {}
    is_final = bool(game.get("isFinal"))
    is_pregame = bool(game.get("isPregame"))

    if is_pregame:
        logger.info(
            "scroll_down_mlb.deck.pregame", extra={"game_id": gid}
        )
        return None

    if is_final:
        existing = await persistence.fetch_official_deck(session, gid)
        if existing is not None:
            logger.info(
                "scroll_down_mlb.deck.served_official",
                extra={
                    "game_id": gid,
                    "deck_version": existing.deck_version,
                },
            )
            return existing

    started = time.monotonic()
    policy = GenerationPolicy.official if is_final else GenerationPolicy.live
    outcome = build_deck_from_upstream(payload, policy=policy)
    duration_ms = int((time.monotonic() - started) * 1000)

    if outcome.blocked:
        logger.warning(
            "scroll_down_mlb.deck.validation_blocked",
            extra={
                "game_id": gid,
                "policy": policy.value,
                "errors": [e.code for e in outcome.errors],
                "duration_ms": duration_ms,
            },
        )
        # Fail closed on official; fail-open on live (live decks already
        # have errors downgraded to warnings by apply_validation_policy).
        return None

    deck = outcome.deck
    if deck is None:
        return None

    if is_final:
        await persistence.upsert_deck(
            session,
            game_id=gid,
            deck=deck,
            warnings=outcome.warnings,
            errors=outcome.errors,
            generator_label="phase5-py-v1",
        )
        await session.commit()
        logger.info(
            "scroll_down_mlb.deck.frozen_official",
            extra={
                "game_id": gid,
                "deck_version": deck.deck_version,
                "card_count": len(deck.cards),
                "duration_ms": duration_ms,
            },
        )
    else:
        logger.info(
            "scroll_down_mlb.deck.built_live",
            extra={
                "game_id": gid,
                "deck_version": deck.deck_version,
                "card_count": len(deck.cards),
                "duration_ms": duration_ms,
            },
        )
    return deck


async def get_game_reveal(
    session: AsyncSession, game_id: str
) -> ScrollDownMlbRevealResponse | None:
    """Return the reveal payload for a final game.

    Live or scheduled games return None (router → 409). Final games
    return finalScore + winnerTeamId + a deterministic recap fallback
    if no recap source is wired up.
    """
    try:
        gid = int(game_id)
    except (TypeError, ValueError):
        return None

    game_row = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.league),
        )
        .where(SportsGame.id == gid)
    )
    game: SportsGame | None = game_row.scalar_one_or_none()
    if game is None or (game.league.code or "").lower() != "mlb":
        return None
    if not GameStatus.is_final_or_post_final_status(game.status):
        return None
    if game.home_score is None or game.away_score is None:
        # Final-status game without a score on file — refuse to fabricate.
        logger.warning(
            "scroll_down_mlb.reveal.missing_score", extra={"game_id": gid}
        )
        return None

    home = game.home_team
    away = game.away_team
    home_won = game.home_score > game.away_score
    is_tie = game.home_score == game.away_score
    winner_team_id: str | None = None
    if not is_tie:
        winner_team_id = str(home.id if home_won else away.id) if (
            home and away
        ) else None

    # Deterministic recap fallback. Phase 5 deliberately avoids an LLM
    # dependency; the gameflow source can be wired in a follow-up.
    if is_tie:
        summary = (
            f"{away.name if away else 'Away'} and "
            f"{home.name if home else 'Home'} ended in a tie, "
            f"{game.away_score}–{game.home_score}."
        )
    else:
        winner_name = (home.name if home_won else away.name) if home and away else "The winner"
        loser_name = (away.name if home_won else home.name) if home and away else "The loser"
        summary = (
            f"{winner_name} beat {loser_name}, "
            f"{max(game.home_score, game.away_score)}–"
            f"{min(game.home_score, game.away_score)}."
        )

    return ScrollDownMlbRevealResponse(
        game_id=str(gid),
        final_score={"home": game.home_score, "away": game.away_score},
        winner_team_id=winner_team_id,
        summary=summary,
        key_stats=[],
        game_flow=[],
        generated_at=datetime.now(UTC),
    )


async def generate_live_deck(payload: dict[str, Any]) -> GenerationOutcome:
    """Build a provisional deck from in-progress play data.

    Live policy: validation errors degrade to warnings — the user must not
    see a blank screen mid-game.
    """
    return build_deck_from_upstream(payload, policy=GenerationPolicy.live)


async def generate_final_deck(payload: dict[str, Any]) -> GenerationOutcome:
    """Build the official deck for a final game. Fails closed on validation
    errors so the canonical deck is never written from bad input."""
    return build_deck_from_upstream(payload, policy=GenerationPolicy.official)


# ---------------------------------------------------------------------------
# Phase 2 stub deck (still used by router until Phase 4 wires upstream)
# ---------------------------------------------------------------------------


def _stub_deck(*, game_id: str, is_final: bool) -> ScrollDownMlbDeckResponse:
    cards: list[ScrollDownMlbDeckCard] = [
        ScrollDownMlbDeckCard(
            id=f"{game_id}-scene",
            type=DeckCardType.scene,
            sort_order=0,
            title="First pitch",
            description="The matchup is set.",
        ),
        ScrollDownMlbDeckCard(
            id=f"{game_id}-play-1",
            type=DeckCardType.play,
            sort_order=1,
            inning=1,
            half="top",
            description="Leadoff strikes out swinging.",
            play=PlayPayload(
                play_id="stub-1",
                event_type="strikeout",
                label="STRIKEOUT",
                description="Strikes out swinging.",
                outs_before=0,
                outs_after=1,
                base_state_before=BaseState(),
                base_state_after=BaseState(),
                score_before=ScoreState(home=0, away=0),
                runs_scored_on_play=0,
            ),
            leverage_tier=0,
        ),
    ]
    return ScrollDownMlbDeckResponse(
        game_id=game_id,
        deck_version="stub-v0",
        generated_at=datetime.now(UTC),
        is_final=is_final,
        cards=cards,
        planner_report=DtoPlannerReport(),
        validation_warnings=[],
    )


__all__ = [
    "apply_validation_policy",
    "build_deck_from_upstream",
    "built_deck_to_dto",
    "generate_final_deck",
    "generate_live_deck",
    "get_game_deck",
    "get_game_reveal",
    "get_recent_games",
]
