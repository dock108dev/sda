from __future__ import annotations

import pytest

from app.feed.prompt_context import build_card_prompt, build_prompt_window
from app.feed.schemas import (
    CardPeriod,
    CardSituation,
    CardTeam,
    NarrativeCard,
    ScoreChange,
)
from app.routers.sports.schemas.common import (
    PlayImportance,
    PlayModeEligibility,
    ScoreObject,
)


def _card(
    *,
    sport: str,
    league: str,
    play_index: int,
    player: str,
    description: str,
    raw: dict,
    source_play_id: str | None = None,
    score_before: ScoreObject | None = None,
    score_change: ScoreChange | None = None,
    score_after: ScoreObject | None = None,
) -> NarrativeCard:
    score_before = score_before or ScoreObject(home=1, away=0)
    score_change = score_change or ScoreChange(home=1, away=0)
    return NarrativeCard(
        id=f"42:{play_index}",
        gameId=42,
        sourcePlayId=str(play_index) if source_play_id is None else source_play_id,
        playIndex=play_index,
        sport=sport,
        league=league,
        tier=1,
        contentDepth="extended",
        modeEligibility=PlayModeEligibility(important=True, standard=True, all=True),
        importance=PlayImportance(
            level="primary",
            rank=1,
            reasons=["scoring"],
            isKeyMoment=True,
            isScoringPlay=True,
        ),
        visualImportance="high",
        period=CardPeriod(ordinal=1, label="P1", type="REG"),
        displayTime="P1 10:00",
        clock="10:00",
        team=CardTeam(abbreviation="HOM", name="Home Team", side="home"),
        scoreBefore=score_before,
        scoreChange=score_change,
        scoreAfter=score_after,
        situation=CardSituation(summary="earned situation", raw=raw),
        leadIn="P1 10:00 - HOM",
        stageSetting="P1 10:00 - HOM",
        headline=f"{player} - key play",
        description=description,
        impact="scoring",
        tags=["Scoring"],
        spoilerLevel="score_change",
    )


def _game() -> dict:
    return {
        "gameId": 42,
        "sport": "ignored",
        "league": "ignored",
        "homeTeam": "Home Team",
        "awayTeam": "Away Team",
        "homeTeamAbbr": "HOM",
        "awayTeamAbbr": "AWY",
        "finalScore": "Home Team 9, Away Team 8",
        "winner": "Home Team",
    }


@pytest.mark.parametrize(
    ("sport", "league", "raw", "template_id", "expected_terms"),
    [
        (
            "baseball",
            "MLB",
            {
                "baseOut": {"outsBefore": 1, "baseStateBefore": "Runners on 1st"},
                "matchup": {"batterName": "Alex Batter", "pitcherName": "Pat Pitcher"},
                "result": {"runsScored": 1},
            },
            "feed-card-mlb-v1",
            ("baseOut", "matchup", "batter", "pitcher"),
        ),
        (
            "hockey",
            "NHL",
            {
                "clock": {"secondsRemaining": 83},
                "score": {"impact": "tying", "marginBefore": 1},
                "strength": {"state": "power_play"},
            },
            "feed-card-nhl-v1",
            ("strength", "score pressure", "special teams", "clock"),
        ),
        (
            "basketball",
            "NBA",
            {
                "lead": {"isLeadChange": True},
                "run": {"label": "8-0 home run"},
                "clutch": {"isClutch": True},
            },
            "feed-card-basketball-v1",
            ("lead", "runs", "clutch", "pressure"),
        ),
        (
            "football",
            "NFL",
            {
                "drive": {
                    "downDistance": "4th & 2",
                    "fieldPosition": {"label": "Opp 18"},
                    "stakes": ["fourth_down", "red_zone"],
                },
                "flags": {"isFourthDownConversion": True},
            },
            "feed-card-football-v1",
            ("drive", "down", "distance", "stakes"),
        ),
    ],
)
def test_sport_prompt_templates_include_only_allowed_card_generation_fields(
    sport: str,
    league: str,
    raw: dict,
    template_id: str,
    expected_terms: tuple[str, ...],
) -> None:
    window = build_prompt_window(
        game=_game(),
        cards=[
            _card(
                sport=sport,
                league=league,
                play_index=1,
                player="Current Player",
                description="Current earned event.",
                raw=raw,
            )
        ],
        current_play_index=1,
    )
    prompt = build_card_prompt(window)

    assert prompt.template_id == template_id
    assert prompt.model_input["allowedOutputFields"] == [
        "lead_in",
        "headline",
        "impact",
        "chapter_label",
        "situation_summary",
    ]
    for term in expected_terms:
        assert term in prompt.user_prompt
    assert "score math" in prompt.user_prompt
    assert "period ordering" in prompt.user_prompt
    assert "play ordering" in prompt.user_prompt
    assert "tier eligibility" in prompt.user_prompt
    assert "base/out calculation" in prompt.user_prompt
    assert "drive state calculation" in prompt.user_prompt
    assert "final result calculation" in prompt.user_prompt


def test_prompt_window_excludes_future_events_final_score_winner_and_unreached_players() -> None:
    current = _card(
        sport="basketball",
        league="NBA",
        play_index=2,
        player="Current Player",
        description="Current Player hits a jumper.",
        raw={"lead": {"isLeadChange": False}, "run": None, "clutch": {"isClutch": False}},
        score_after=ScoreObject(home=2, away=0),
    )
    future = _card(
        sport="basketball",
        league="NBA",
        play_index=7,
        player="Future Player",
        description="Future Player wins it later, final score 9-8.",
        raw={"lead": {"isLeadChange": True}, "clutch": {"isClutch": True}},
        score_after=ScoreObject(home=9, away=8),
    )

    window = build_prompt_window(
        game=_game(),
        cards=[future, current],
        current_play_index=2,
    )
    prompt = build_card_prompt(window)

    assert prompt.model_input["currentPlayIndex"] == 2
    assert prompt.model_input["priorCards"] == []
    assert "Current Player hits a jumper" in prompt.user_prompt
    assert "Future Player" not in prompt.user_prompt
    assert "wins it later" not in prompt.user_prompt
    assert "final score 9-8" not in prompt.user_prompt
    assert "finalScore" not in prompt.user_prompt
    assert '"winner"' not in prompt.user_prompt
    assert "scoreAfter" not in prompt.user_prompt


@pytest.mark.parametrize(
    ("sport", "league", "raw"),
    [
        ("baseball", "MLB", {"matchup": {"batterName": "Current Player"}}),
        ("hockey", "NHL", {"event": {"playerName": "Current Player"}}),
        ("basketball", "NBA", {"result": {"playerName": "Current Player"}}),
        ("football", "NFL", {"drive": {"runnerName": "Current Player"}}),
    ],
)
def test_prompt_window_excludes_future_plays_for_supported_sports(
    sport: str,
    league: str,
    raw: dict,
) -> None:
    current = _card(
        sport=sport,
        league=league,
        play_index=4,
        player="Current Player",
        description="Current Player creates a middle-game card.",
        raw=raw,
    )
    future = _card(
        sport=sport,
        league=league,
        play_index=8,
        player="Future Player",
        description="Future Player closes the game later.",
        raw={"result": {"playerName": "Future Player"}},
        score_after=ScoreObject(home=9, away=8),
    )

    prompt = build_card_prompt(
        build_prompt_window(game=_game(), cards=[future, current], current_play_index=4)
    )

    assert prompt.model_input["currentPlayIndex"] == 4
    assert "Current Player creates a middle-game card" in prompt.user_prompt
    assert "Future Player" not in prompt.user_prompt
    assert "closes the game later" not in prompt.user_prompt
    assert "scoreAfter" not in prompt.user_prompt


def test_context_window_falls_back_to_sequence_for_duplicate_and_missing_source_ids() -> None:
    first = _card(
        sport="basketball",
        league="NBA",
        play_index=1,
        source_play_id="provider-1",
        player="First Player",
        description="First Player scores.",
        raw={},
        score_before=ScoreObject(home=0, away=0),
        score_change=ScoreChange(home=1, away=0),
    )
    duplicate = _card(
        sport="basketball",
        league="NBA",
        play_index=2,
        source_play_id="provider-1",
        player="Second Player",
        description="Second Player follows.",
        raw={},
        score_before=ScoreObject(home=1, away=0),
        score_change=ScoreChange(home=0, away=0),
    )
    missing_and_corrected = _card(
        sport="basketball",
        league="NBA",
        play_index=4,
        source_play_id="",
        player="Fourth Player",
        description="Fourth Player resumes after a correction.",
        raw={},
        score_before=ScoreObject(home=5, away=0),
        score_change=ScoreChange(home=0, away=0),
    )

    window = build_prompt_window(
        game=_game(),
        cards=[missing_and_corrected, duplicate, first],
        current_play_index=4,
    )

    assert window.ordering["orderedPlayKeys"] == ["sequence:1", "sequence:2", "sequence:4"]
    assert window.ordering["duplicateSourcePlayIds"] == ["provider-1"]
    assert window.ordering["missingSourcePlayIndices"] == [4]
    assert window.ordering["skippedPlayIndices"] == [3]
    assert window.ordering["scoreCorrectionPlayIndices"] == [4]
    assert window.current_card["stablePlayKey"] == "sequence:4"
    assert {
        "duplicate_source_ids_fallback_to_sequence",
        "missing_source_ids_fallback_to_sequence",
        "skipped_play_indices_present",
        "score_corrections_present",
    } <= set(window.regeneration["reasonCodes"])


def test_context_hash_is_stable_and_changes_when_prior_live_play_is_inserted() -> None:
    first = _card(
        sport="football",
        league="NFL",
        play_index=1,
        source_play_id="snap-1",
        player="First Player",
        description="First Player opens the drive.",
        raw={"drive": {"downDistance": "1st & 10"}},
        score_before=ScoreObject(home=0, away=0),
        score_change=ScoreChange(home=0, away=0),
    )
    current = _card(
        sport="football",
        league="NFL",
        play_index=3,
        source_play_id="snap-3",
        player="Current Player",
        description="Current Player scores.",
        raw={"drive": {"downDistance": "3rd & goal"}},
        score_before=ScoreObject(home=0, away=0),
        score_change=ScoreChange(home=7, away=0),
    )
    inserted = _card(
        sport="football",
        league="NFL",
        play_index=2,
        source_play_id="snap-2",
        player="Inserted Player",
        description="Inserted Player converts.",
        raw={"drive": {"downDistance": "2nd & 4"}},
        score_before=ScoreObject(home=0, away=0),
        score_change=ScoreChange(home=0, away=0),
    )

    original = build_prompt_window(game=_game(), cards=[first, current], current_play_index=3)
    same = build_prompt_window(game=_game(), cards=[current, first], current_play_index=3)
    updated = build_prompt_window(
        game=_game(),
        cards=[first, inserted, current],
        current_play_index=3,
    )

    assert same.regeneration["contextHash"] == original.regeneration["contextHash"]
    assert updated.regeneration["contextHash"] != original.regeneration["contextHash"]
    assert updated.regeneration["currentCardId"] == original.regeneration["currentCardId"]
    assert updated.regeneration["currentPlayKey"] == "source:snap-3"
    assert updated.prior_cards[-1]["playIndex"] == 2
    assert updated.current_card["playIndex"] == 3


def test_prompt_window_keeps_prior_earned_cards_and_rejects_missing_current_card() -> None:
    prior = _card(
        sport="football",
        league="NFL",
        play_index=1,
        player="Prior Player",
        description="Prior Player converts on fourth down.",
        raw={"drive": {"downDistance": "4th & 1"}},
    )
    current = _card(
        sport="football",
        league="NFL",
        play_index=3,
        player="Current Player",
        description="Current Player scores in the red zone.",
        raw={"drive": {"fieldPosition": {"label": "Opp 5"}, "stakes": ["red_zone"]}},
    )

    window = build_prompt_window(game=_game(), cards=[current, prior], current_play_index=3)

    assert [card["playIndex"] for card in window.prior_cards] == [1]
    assert window.current_card["playIndex"] == 3
    with pytest.raises(ValueError, match="No card exists"):
        build_prompt_window(game=_game(), cards=[current, prior], current_play_index=2)
