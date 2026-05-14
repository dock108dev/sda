"""Unit tests for the cross-game daily pressure pack selection service."""

from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.scroll_down_mlb.arcade_pack_service import (
    DEFAULT_PACK_SIZE,
    DailyPressurePack,
    NoPressurePackAvailable,
    _Candidate,
    build_daily_pressure_pack,
    collect_candidates,
    score_candidate,
)


def _run(coro):
    return asyncio.run(coro)


def _play_card(
    *,
    play_index: int,
    inning: int = 9,
    half: str = "bottom",
    outs_before: int = 1,
    bases: tuple[bool, bool, bool] = (False, False, False),
    score_before: tuple[int, int] = (3, 3),
    score_change: tuple[int, int] = (0, 0),
    leverage_tier: int | None = 2,
) -> dict[str, Any]:
    home_before, away_before = score_before
    home_delta, away_delta = score_change
    return {
        "id": f"123-{play_index}",
        "type": "play",
        "sortOrder": play_index,
        "inning": inning,
        "half": half,
        "title": f"{half.title()} {inning}",
        "description": "Test play",
        "leverageTier": leverage_tier,
        "play": {
            "playId": str(play_index),
            "outsBefore": outs_before,
            "baseStateBefore": {
                "first": bases[0],
                "second": bases[1],
                "third": bases[2],
            },
            "scoreBefore": {"home": home_before, "away": away_before},
            "scoreChange": {"home": home_delta, "away": away_delta},
        },
    }


def _scene_card(card_id: str = "scene-1") -> dict[str, Any]:
    return {"id": card_id, "type": "scene", "description": "First pitch"}


def _rhythm_card(card_id: str = "rhythm-1") -> dict[str, Any]:
    return {"id": card_id, "type": "rhythm", "description": "Mid-inning break"}


def _deck_row(*, game_id: int, cards: list[dict[str, Any]]) -> Any:
    """Build a duck-typed ``ScrollDownMlbDeck`` stand-in for tests.

    The service reads only ``.game_id`` and ``.payload_json`` on each row;
    a ``SimpleNamespace`` matches that surface without dragging in the
    SQLAlchemy mapper instrumentation.
    """
    return SimpleNamespace(game_id=game_id, payload_json={"cards": cards})


def _session_returning(decks: list[Any]) -> Any:
    """Build a mock ``AsyncSession`` whose ``execute().scalars().all()``
    returns ``decks``."""
    scalars = SimpleNamespace(all=lambda: list(decks))
    result = SimpleNamespace(scalars=lambda: scalars)
    return SimpleNamespace(execute=AsyncMock(return_value=result))


# ---------------------------------------------------------------------------
# build_daily_pressure_pack — DB-facing async path
# ---------------------------------------------------------------------------


def test_zero_decks_for_date_raises_no_pressure_pack_available() -> None:
    session = _session_returning([])
    target = datetime.date(2026, 5, 13)
    with pytest.raises(NoPressurePackAvailable) as exc:
        _run(build_daily_pressure_pack(target, session))
    assert exc.value.date == target
    assert "2026-05-13" in str(exc.value)


def test_three_high_leverage_plays_returns_three_moment_pack() -> None:
    decks = [
        _deck_row(
            game_id=g,
            cards=[
                _scene_card(f"scene-{g}"),
                _play_card(
                    play_index=10,
                    inning=9,
                    half="bottom",
                    outs_before=2,
                    bases=(True, True, True),
                    score_before=(2, 2),
                    score_change=(1, 0),
                    leverage_tier=2,
                ),
            ],
        )
        for g in (101, 102, 103)
    ]
    session = _session_returning(decks)
    pack = _run(build_daily_pressure_pack(datetime.date(2026, 5, 13), session))
    assert isinstance(pack, DailyPressurePack)
    assert len(pack.moments) == 3
    # Ranks are 1-based and contiguous.
    assert [m.rank for m in pack.moments] == [1, 2, 3]
    # All three moments come from different games.
    assert {m.game_id for m in pack.moments} == {101, 102, 103}
    # Difficulty is sorted descending (ties broken by game_id ascending).
    assert pack.moments[0].difficulty >= pack.moments[1].difficulty
    assert pack.moments[1].difficulty >= pack.moments[2].difficulty


def test_more_than_five_candidates_trimmed_to_default_pack_size() -> None:
    # One deck with 7 play cards across one game; difficulties vary by
    # leverage_tier so the top-5 cut is observable.
    cards: list[dict[str, Any]] = [_scene_card()]
    for idx, tier in enumerate([0, 1, 2, 0, 1, 2, 1], start=1):
        cards.append(
            _play_card(
                play_index=idx,
                inning=5 + idx,
                outs_before=1,
                bases=(False, True, False),
                score_before=(1, 1),
                score_change=(1, 0) if idx % 2 == 0 else (0, 0),
                leverage_tier=tier,
            )
        )
    session = _session_returning([_deck_row(game_id=999, cards=cards)])
    pack = _run(build_daily_pressure_pack(datetime.date(2026, 5, 13), session))
    assert len(pack.moments) == DEFAULT_PACK_SIZE


def test_decks_with_only_non_play_cards_raise_no_pressure_pack_available() -> None:
    decks = [
        _deck_row(game_id=200, cards=[_scene_card(), _rhythm_card()]),
        _deck_row(game_id=201, cards=[_scene_card("scene-2")]),
    ]
    session = _session_returning(decks)
    with pytest.raises(NoPressurePackAvailable):
        _run(build_daily_pressure_pack(datetime.date(2026, 5, 13), session))


def test_pack_size_override_caps_moments() -> None:
    cards = [_scene_card()]
    for idx in range(1, 6):
        cards.append(
            _play_card(
                play_index=idx,
                inning=8,
                outs_before=1,
                bases=(False, True, False),
                score_before=(2, 2),
                score_change=(1, 0),
                leverage_tier=2,
            )
        )
    session = _session_returning([_deck_row(game_id=300, cards=cards)])
    pack = _run(
        build_daily_pressure_pack(
            datetime.date(2026, 5, 13), session, pack_size=2
        )
    )
    assert len(pack.moments) == 2


def test_pack_size_zero_still_returns_at_least_one_moment() -> None:
    # Defensive: pack_size=0 is invalid for an arcade experience; the
    # service clamps to a minimum of one moment.
    session = _session_returning(
        [
            _deck_row(
                game_id=400,
                cards=[_play_card(play_index=1, leverage_tier=2)],
            )
        ]
    )
    pack = _run(
        build_daily_pressure_pack(
            datetime.date(2026, 5, 13), session, pack_size=0
        )
    )
    assert len(pack.moments) == 1


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_duplicate_game_play_pairs_are_collapsed_before_scoring() -> None:
    duplicated_card = _play_card(play_index=42, leverage_tier=2)
    decks = [
        _deck_row(game_id=500, cards=[duplicated_card]),
        _deck_row(game_id=500, cards=[duplicated_card]),
        _deck_row(
            game_id=500,
            cards=[_play_card(play_index=43, leverage_tier=2)],
        ),
    ]
    cands = collect_candidates(decks)
    assert {(c.game_id, c.play_index) for c in cands} == {(500, 42), (500, 43)}
    assert len(cands) == 2


def test_collect_candidates_skips_non_play_and_malformed_cards() -> None:
    deck = _deck_row(
        game_id=600,
        cards=[
            _scene_card(),
            _rhythm_card(),
            {"type": "play"},  # missing play dict
            {"type": "play", "play": {"playId": "not-an-int"}},
            "not-a-dict-at-all",  # type: ignore[list-item]
            _play_card(play_index=7),
        ],
    )
    cands = collect_candidates([deck])
    assert len(cands) == 1
    assert cands[0].play_index == 7


def test_collect_candidates_keeps_first_occurrence_when_duplicated() -> None:
    first = _play_card(play_index=11, leverage_tier=2)
    second = _play_card(play_index=11, leverage_tier=0)
    deck = _deck_row(game_id=700, cards=[first, second])
    cands = collect_candidates([deck])
    assert len(cands) == 1
    assert cands[0].card["leverageTier"] == 2


# ---------------------------------------------------------------------------
# Scoring derivations from the wire card
# ---------------------------------------------------------------------------


def test_score_candidate_recognises_tying_run_scored() -> None:
    # Away team trailing 2-3 scores a single run; this ties the game and
    # should register as a tying play in the derived flags.
    card = _play_card(
        play_index=1,
        inning=9,
        half="top",
        outs_before=2,
        bases=(False, True, False),
        score_before=(3, 2),
        score_change=(0, 1),
        leverage_tier=2,
    )
    cand = _Candidate(game_id=1, play_index=1, card=card)
    score = score_candidate(cand)
    # A tying late-inning play with a runner on, 2 outs, climactic leverage
    # comfortably clears the high-pressure tier (>= 65).
    assert score >= 65


def test_score_candidate_recognises_lead_change() -> None:
    # Home down 1-2, batter doubles in two: lead flips from -1 to +1.
    card = _play_card(
        play_index=2,
        inning=8,
        half="bottom",
        outs_before=1,
        bases=(True, True, False),
        score_before=(1, 2),
        score_change=(2, 0),
        leverage_tier=2,
    )
    cand = _Candidate(game_id=1, play_index=2, card=card)
    assert score_candidate(cand) >= 70


def test_score_candidate_routine_blowout_scores_low() -> None:
    card = _play_card(
        play_index=3,
        inning=3,
        half="top",
        outs_before=0,
        bases=(False, False, False),
        score_before=(8, 1),
        score_change=(0, 0),
        leverage_tier=0,
    )
    cand = _Candidate(game_id=1, play_index=3, card=card)
    assert score_candidate(cand) <= 40


def test_score_candidate_tolerates_missing_optional_fields() -> None:
    # Bare-minimum card — exercise the defensive coercions.
    card = {
        "type": "play",
        "inning": 5,
        "play": {"playId": "5"},
    }
    cand = _Candidate(game_id=9, play_index=5, card=card)
    score = score_candidate(cand)
    assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# Sorting / ranking
# ---------------------------------------------------------------------------


def test_moments_sorted_by_difficulty_descending() -> None:
    # Three plays with monotonically increasing leverage so scores differ.
    cards = [
        _play_card(
            play_index=1, inning=3, leverage_tier=0,
            bases=(False, False, False), score_before=(5, 1),
        ),
        _play_card(
            play_index=2, inning=7, leverage_tier=1,
            bases=(False, True, False), score_before=(2, 2),
        ),
        _play_card(
            play_index=3, inning=9, leverage_tier=2,
            bases=(True, True, True), score_before=(3, 3),
            score_change=(1, 0), outs_before=2,
        ),
    ]
    session = _session_returning([_deck_row(game_id=42, cards=cards)])
    pack = _run(build_daily_pressure_pack(datetime.date(2026, 5, 13), session))
    diffs = [m.difficulty for m in pack.moments]
    assert diffs == sorted(diffs, reverse=True)
    # The walk-off-style climactic play (play_index=3) leads the pack.
    assert pack.moments[0].play_index == 3
