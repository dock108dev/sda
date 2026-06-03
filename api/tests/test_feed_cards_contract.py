from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.db.sports import GameStatus, SportsGamePlay, SportsTeam
from app.feed.schemas import CardFeedResponse, CardFeedStatus, SpoilerPolicy
from app.feed.service import build_card_feed_from_game


def _team(
    *,
    team_id: int,
    league_id: int,
    name: str,
    abbreviation: str,
) -> SportsTeam:
    return SportsTeam(
        id=team_id,
        league_id=league_id,
        name=name,
        short_name=name,
        abbreviation=abbreviation,
    )


def _game(
    *,
    league: str,
    play_type: str,
    description: str,
    home_score: int,
    away_score: int,
    status: str = GameStatus.final.value,
    game_id: int = 42,
    quarter: int | None = None,
    play_index: int = 7,
) -> SimpleNamespace:
    home = _team(team_id=1, league_id=1, name=f"{league} Home", abbreviation="HOM")
    away = _team(team_id=2, league_id=1, name=f"{league} Away", abbreviation="AWY")
    play = SportsGamePlay(
        game_id=game_id,
        quarter=quarter or (4 if league in {"NBA", "NFL"} else 3),
        game_clock="01:23",
        play_index=play_index,
        play_type=play_type,
        team=home,
        player_name="Alex Morgan",
        description=description,
        home_score=home_score,
        away_score=away_score,
        raw_data={},
    )
    return SimpleNamespace(
        id=game_id,
        league=SimpleNamespace(code=league),
        home_team=home,
        away_team=away,
        home_score=home_score,
        away_score=away_score,
        plays=[play],
        team_boxscores=[],
        player_boxscores=[],
        status=status,
        last_pbp_at=None,
        last_ingested_at=None,
    )


def _play(
    *,
    game_id: int,
    quarter: int,
    play_index: int,
    play_type: str,
    team: SportsTeam,
    description: str,
    home_score: int,
    away_score: int,
) -> SportsGamePlay:
    return SportsGamePlay(
        game_id=game_id,
        quarter=quarter,
        game_clock="01:23",
        play_index=play_index,
        play_type=play_type,
        team=team,
        player_name="Alex Morgan",
        description=description,
        home_score=home_score,
        away_score=away_score,
        raw_data={},
    )


@pytest.mark.parametrize(
    ("league", "play_type", "sport"),
    [
        ("MLB", "home_run", "baseball"),
        ("NHL", "goal", "hockey"),
        ("NBA", "3pt_made", "basketball"),
        ("NFL", "touchdown", "football"),
    ],
)
def test_card_feed_has_required_json_contract_for_supported_sports(
    league: str,
    play_type: str,
    sport: str,
) -> None:
    feed = build_card_feed_from_game(
        _game(
            league=league,
            play_type=play_type,
            description=f"{league} scoring play",
            home_score=2,
            away_score=0,
        ),
        SpoilerPolicy.pre_reveal,
    )
    body = feed.model_dump(by_alias=True, mode="json", exclude_none=True)

    assert CardFeedResponse.model_validate(body)
    assert body["contractVersion"] == 2
    assert body["game"]["sport"] == sport
    assert body["game"]["league"] == league
    assert body["game"]["homeTeamId"] == 1
    assert body["game"]["awayTeamId"] == 2
    assert body["generation"] == {
        "status": "ready",
        "cardCount": 1,
        "lastPlayIndex": 7,
        "generatedAt": body["generation"]["generatedAt"],
        "isStale": False,
        "validationIssues": [],
    }
    assert body["reveal"] == {
        "available": True,
        "status": "ready",
        "scoresInCards": False,
        "revealRequiredForScores": True,
        "completedGameBoundary": {
            "finalScore": "hidden_until_reveal",
            "winner": "hidden_until_reveal",
            "stats": "hidden_until_reveal",
            "payoffCopy": "hidden_until_reveal",
        },
    }
    assert body["sections"] == [
        {
            "id": body["sections"][0]["id"],
            "kind": "period",
            "ordinal": 1,
            "period": body["cards"][0]["period"],
            "label": body["cards"][0]["period"]["label"],
            "title": body["sections"][0]["title"],
            "leadIn": body["sections"][0]["leadIn"],
            "startPlayIndex": 7,
            "endPlayIndex": 7,
            "textFieldSpoilerLevel": "earnedAtPlay",
            "source": "deterministic",
        }
    ]
    assert body["sections"][0]["title"]
    assert body["sections"][0]["leadIn"].endswith("opens the feed.")

    card = body["cards"][0]
    assert {
        "id",
        "gameId",
        "sourcePlayId",
        "playIndex",
        "sport",
        "league",
        "tier",
        "contentDepth",
        "modeEligibility",
        "importance",
        "visualImportance",
        "period",
        "displayTime",
        "clock",
        "team",
        "scoreBefore",
        "scoreChange",
        "situation",
        "leadIn",
        "stageSetting",
        "headline",
        "description",
        "impact",
        "tags",
        "spoilerLevel",
        "textFieldSpoilerLevels",
    } <= set(card)
    assert "scoreAfter" not in card
    assert card["scoreBefore"] == {"home": 0, "away": 0}
    assert card["scoreChange"] == {"home": 2, "away": 0}
    assert card["team"] == {"abbreviation": "HOM", "name": f"{league} Home", "side": "home"}
    assert card["modeEligibility"]["all"] is True
    assert card["importance"]["level"] in {"primary", "secondary", "tertiary"}
    assert card["visualImportance"] in {"critical", "high", "medium", "low"}
    assert card["textFieldSpoilerLevels"] == {
        "leadIn": "earnedAtPlay",
        "stageSetting": "earnedAtPlay",
        "headline": "earnedAtPlay",
        "description": "earnedAtPlay",
        "impact": "earnedAtPlay",
        "situationSummary": "earnedAtPlay",
        "tags": "earnedAtPlay",
    }


def test_card_feed_revealed_policy_includes_score_after() -> None:
    feed = build_card_feed_from_game(
        _game(
            league="NBA",
            play_type="layup",
            description="Made layup",
            home_score=2,
            away_score=0,
        ),
        SpoilerPolicy.revealed,
    )
    body = feed.model_dump(by_alias=True, mode="json", exclude_none=True)
    card = body["cards"][0]

    assert card["scoreAfter"] == {"home": 2, "away": 0}
    assert card["spoilerLevel"] == "score_revealed"
    assert body["reveal"] == {
        "available": True,
        "status": "ready",
        "scoresInCards": True,
        "revealRequiredForScores": False,
        "completedGameBoundary": {
            "finalScore": "allowed",
            "winner": "allowed",
            "stats": "allowed",
            "payoffCopy": "allowed",
        },
    }


def test_card_feed_revealed_policy_includes_current_score_and_stats() -> None:
    game = _game(
        league="NBA",
        play_type="layup",
        description="Made layup",
        home_score=52,
        away_score=50,
        status=GameStatus.live.value,
    )
    game.team_boxscores = [
        SimpleNamespace(
            team=game.away_team,
            is_home=False,
            stats={"rebounds": 20},
            source=None,
            updated_at=None,
        ),
        SimpleNamespace(
            team=game.home_team,
            is_home=True,
            stats={"rebounds": 22},
            source=None,
            updated_at=None,
        ),
    ]
    game.player_boxscores = [
        SimpleNamespace(
            team=game.home_team,
            player_name="Alex Morgan",
            stats={"points": 14, "rebounds": 5, "assists": 3},
            source=None,
            updated_at=None,
        )
    ]

    body = build_card_feed_from_game(game, SpoilerPolicy.revealed).model_dump(
        by_alias=True,
        mode="json",
        exclude_none=True,
    )

    assert body["game"]["score"] == {"home": 52, "away": 50}
    assert [stat["team"] for stat in body["teamStats"]] == ["NBA Away", "NBA Home"]
    assert body["playerStats"][0]["playerName"] == "Alex Morgan"
    assert body["playerStats"][0]["points"] == 14


def test_card_feed_limits_response_to_requested_play_window() -> None:
    game = _game(
        league="NBA",
        play_type="layup",
        description="Alex Morgan opens the scoring.",
        home_score=2,
        away_score=0,
        quarter=1,
        play_index=1,
    )
    game.home_score = 9
    game.away_score = 8
    game.plays.append(
        _play(
            game_id=game.id,
            quarter=4,
            play_index=2,
            play_type="jump_shot",
            team=game.away_team,
            description="Dax Moreno hits the eventual winner for the 9-8 final.",
            home_score=9,
            away_score=8,
        )
    )
    game.plays[-1].player_name = "Dax Moreno"

    feed = build_card_feed_from_game(
        game,
        SpoilerPolicy.pre_reveal,
        through_play_index=1,
    )
    body = feed.model_dump(by_alias=True, mode="json", exclude_none=True)
    payload = json.dumps(body["cards"])

    assert body["generation"]["cardCount"] == 1
    assert body["generation"]["lastPlayIndex"] == 1
    assert [card["playIndex"] for card in body["cards"]] == [1]
    assert "Dax Moreno" not in payload
    assert "9-8" not in payload
    assert "winner" not in payload.lower()


def test_card_feed_emits_stable_period_lead_ins_without_future_section_context() -> None:
    game = _game(
        league="NBA",
        play_type="layup",
        description="Alex Morgan opens the scoring.",
        home_score=2,
        away_score=0,
        quarter=1,
        play_index=1,
    )
    game.home_score = 12
    game.away_score = 10
    game.plays.append(
        _play(
            game_id=game.id,
            quarter=2,
            play_index=2,
            play_type="jump_shot",
            team=game.away_team,
            description="Blake Rivers makes a jumper.",
            home_score=2,
            away_score=2,
        )
    )
    game.plays.append(
        _play(
            game_id=game.id,
            quarter=4,
            play_index=3,
            play_type="jump_shot",
            team=game.away_team,
            description="Dax Moreno hits the eventual winner for the 12-10 final.",
            home_score=12,
            away_score=10,
        )
    )
    game.plays[-1].player_name = "Dax Moreno"

    body = build_card_feed_from_game(
        game,
        SpoilerPolicy.pre_reveal,
        through_play_index=2,
    ).model_dump(by_alias=True, mode="json", exclude_none=True)

    assert [section["label"] for section in body["sections"]] == ["Q1", "Q2"]
    assert body["sections"][0]["id"].endswith(":period:1:q1")
    assert body["sections"][0]["leadIn"] == "First quarter opens the feed."
    assert body["sections"][1]["leadIn"] == "Second quarter begins after 1 earlier play."
    assert "Dax Moreno" not in json.dumps(body["sections"])
    assert "12-10" not in json.dumps(body["sections"])


def test_pre_reveal_card_redacts_reveal_only_score_pressure_metadata() -> None:
    game = _game(
        league="NBA",
        play_type="made_shot",
        description="Away Builder scores.",
        home_score=87,
        away_score=88,
        quarter=3,
        play_index=1,
    )
    game.plays.append(
        _play(
            game_id=game.id,
            quarter=3,
            play_index=2,
            play_type="3pt_made",
            team=game.home_team,
            description="Lead Flipper makes a three.",
            home_score=90,
            away_score=88,
        )
    )
    game.plays[-1].player_name = "Lead Flipper"

    body = build_card_feed_from_game(
        game,
        SpoilerPolicy.pre_reveal,
    ).model_dump(by_alias=True, mode="json", exclude_none=True)
    card = body["cards"][1]
    raw = card["situation"]["raw"]
    payload = json.dumps(card).lower()

    assert card["impact"] == "scoring"
    assert "lead" not in raw
    assert "marginAfter" not in payload
    assert "isLeadChange" not in payload
    assert "lead change" not in payload
    assert card["textFieldSpoilerLevels"]["impact"] == "earnedAtPlay"


def test_card_feed_reveal_boundary_is_unavailable_before_completed_games() -> None:
    feed = build_card_feed_from_game(
        _game(
            league="NHL",
            play_type="shot",
            description="Shot on goal.",
            home_score=0,
            away_score=0,
            status=GameStatus.live.value,
        ),
        SpoilerPolicy.pre_reveal,
    )
    reveal = feed.model_dump(by_alias=True, mode="json", exclude_none=True)["reveal"]

    assert reveal["available"] is False
    assert reveal["status"] == "unavailable"
    assert reveal["completedGameBoundary"] == {
        "finalScore": "unavailable",
        "winner": "unavailable",
        "stats": "unavailable",
        "payoffCopy": "unavailable",
    }


def test_card_feed_falls_back_when_text_mentions_future_spoilers() -> None:
    game = _game(
        league="NBA",
        play_type="layup",
        description="Alex Morgan would eventually seal the 4-2 win before Dax Moreno arrived.",
        home_score=1,
        away_score=0,
        quarter=1,
        play_index=1,
    )
    game.plays.append(
        _play(
            game_id=game.id,
            quarter=4,
            play_index=2,
            play_type="jump_shot",
            team=game.away_team,
            description="Dax Moreno hits a jumper.",
            home_score=4,
            away_score=2,
        )
    )
    game.plays[-1].player_name = "Dax Moreno"
    game.home_score = 4
    game.away_score = 2

    feed = build_card_feed_from_game(game, SpoilerPolicy.pre_reveal)
    body = feed.model_dump(by_alias=True, mode="json", exclude_none=True)

    assert body["generation"]["status"] == "ready"
    assert {
        "narrative_future_spoiler_phrase",
        "narrative_final_score_leak",
        "narrative_winner_leak",
        "narrative_future_player_mention",
    } <= set(body["generation"]["validationIssues"])
    assert body["cards"][0]["description"] == "Verified play detail is available after reveal."


def test_card_feed_allows_current_official_description_player_mentions() -> None:
    game = _game(
        league="MLB",
        play_type="double_play",
        description=(
            "Alex Morgan lines into a double play, center fielder Dax Moreno "
            "to catcher Blake Rivers. The runner is retired."
        ),
        home_score=0,
        away_score=0,
        quarter=2,
        play_index=15005,
    )
    later_fielder_play = _play(
        game_id=game.id,
        quarter=3,
        play_index=20008,
        play_type="single",
        team=game.home_team,
        description="Dax Moreno singles.",
        home_score=0,
        away_score=0,
    )
    later_fielder_play.player_name = "Dax Moreno"
    later_catcher_play = _play(
        game_id=game.id,
        quarter=3,
        play_index=20009,
        play_type="single",
        team=game.home_team,
        description="Blake Rivers singles.",
        home_score=0,
        away_score=0,
    )
    later_catcher_play.player_name = "Blake Rivers"
    game.plays.extend([later_fielder_play, later_catcher_play])

    feed = build_card_feed_from_game(game, SpoilerPolicy.pre_reveal)
    body = feed.model_dump(by_alias=True, mode="json", exclude_none=True)

    assert "narrative_future_player_mention" not in body["generation"]["validationIssues"]
    assert body["cards"][0]["description"] == game.plays[0].description


def test_important_card_carries_stream_importance_density_and_narrative_fields() -> None:
    feed = build_card_feed_from_game(
        _game(
            league="MLB",
            play_type="home_run",
            description="Alex Morgan homers to center field.",
            home_score=2,
            away_score=0,
        ),
        SpoilerPolicy.pre_reveal,
    )
    card = feed.model_dump(by_alias=True, mode="json", exclude_none=True)["cards"][0]

    assert card["modeEligibility"] == {"important": True, "standard": True, "all": True}
    assert card["importance"]["level"] == "primary"
    assert card["contentDepth"] == "extended"
    assert card["visualImportance"] == "high"
    assert card["stageSetting"] != card["leadIn"]
    assert card["stageSetting"]
    assert "bases empty" in card["stageSetting"].lower()
    assert card["headline"] == "Alex Morgan - Home run"
    assert card["description"] == "Alex Morgan homers to center field."
    assert card["impact"] == "HOM scores 2"
    assert {"Home run", "Scoring"} <= set(card["tags"])


def test_standard_card_uses_backend_membership_without_changing_density_shape() -> None:
    game = _game(
        league="NBA",
        play_type="layup",
        description="Alex Morgan makes a layup.",
        home_score=2,
        away_score=0,
        quarter=1,
        play_index=1,
    )
    game.plays.append(
        _play(
            game_id=game.id,
            quarter=1,
            play_index=2,
            play_type="defensive_rebound",
            team=game.away_team,
            description="AWY defensive rebound.",
            home_score=2,
            away_score=0,
        )
    )

    feed = build_card_feed_from_game(game, SpoilerPolicy.pre_reveal)
    card = feed.model_dump(by_alias=True, mode="json", exclude_none=True)["cards"][0]

    assert card["modeEligibility"] == {"important": False, "standard": True, "all": True}
    assert card["importance"]["level"] == "secondary"
    assert card["contentDepth"] == "standard"
    assert card["visualImportance"] == "medium"
    assert card["description"] == "Alex Morgan makes a layup."
    assert card["period"]["label"]
    assert card["clock"] == "01:23"
    assert card["situation"]["summary"]
    assert len(card["tags"]) <= 3


def test_basic_card_keeps_all_play_membership_and_uses_clean_detail_text() -> None:
    game = _game(
        league="NHL",
        play_type="neutral_zone_faceoff",
        description="NEUTRAL_ZONE_FACEOFF",
        home_score=0,
        away_score=0,
        quarter=1,
        play_index=1,
    )
    game.plays.append(
        _play(
            game_id=game.id,
            quarter=1,
            play_index=2,
            play_type="shot",
            team=game.away_team,
            description="Shot wide.",
            home_score=0,
            away_score=0,
        )
    )

    feed = build_card_feed_from_game(game, SpoilerPolicy.pre_reveal)
    card = feed.model_dump(by_alias=True, mode="json", exclude_none=True)["cards"][0]

    assert card["modeEligibility"] == {"important": False, "standard": False, "all": True}
    assert card["importance"]["level"] == "tertiary"
    assert card["contentDepth"] == "brief"
    assert card["visualImportance"] == "low"
    assert card["description"] == "Neutral zone faceoff"
    assert "_" not in card["description"]
    assert card["tags"] == ["Neutral zone faceoff"]


def test_card_feed_returns_renderable_status_for_empty_and_unsupported_games() -> None:
    empty_game = _game(
        league="NHL",
        play_type="goal",
        description="Goal",
        home_score=1,
        away_score=0,
    )
    empty_game.plays = []
    empty_feed = build_card_feed_from_game(empty_game, SpoilerPolicy.pre_reveal)

    assert empty_feed.generation.status is CardFeedStatus.no_pbp_yet
    assert empty_feed.generation.card_count == 0
    assert empty_feed.cards == []

    unsupported_game = _game(
        league="MLS",
        play_type="goal",
        description="Goal",
        home_score=1,
        away_score=0,
    )
    unsupported_feed = build_card_feed_from_game(unsupported_game, SpoilerPolicy.pre_reveal)

    assert unsupported_feed.generation.status is CardFeedStatus.unsupported_sport
    assert unsupported_feed.cards == []


def test_card_feed_exposes_pending_blocked_and_stale_states() -> None:
    pending = build_card_feed_from_game(
        _game(
            league="MLB",
            play_type="single",
            description="Single",
            home_score=0,
            away_score=0,
            status=GameStatus.recap_pending.value,
        ),
        SpoilerPolicy.pre_reveal,
    )
    blocked = build_card_feed_from_game(
        _game(
            league="MLB",
            play_type="single",
            description="Single",
            home_score=0,
            away_score=0,
            status=GameStatus.recap_failed.value,
        ),
        SpoilerPolicy.pre_reveal,
    )
    stale_game = _game(
        league="NBA",
        play_type="foul",
        description="Foul",
        home_score=0,
        away_score=0,
        status=GameStatus.live.value,
    )
    stale_game.last_ingested_at = datetime(2026, 1, 1, tzinfo=UTC)
    stale_game.last_pbp_at = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    stale = build_card_feed_from_game(stale_game, SpoilerPolicy.pre_reveal)

    assert pending.generation.status is CardFeedStatus.generation_pending
    assert pending.cards == []
    assert blocked.generation.status is CardFeedStatus.validation_blocked
    assert blocked.generation.validation_issues
    assert stale.generation.status is CardFeedStatus.stale_regenerating
    assert stale.generation.is_stale is True
    assert stale.cards
