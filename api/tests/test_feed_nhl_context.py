from __future__ import annotations

from types import SimpleNamespace

from app.db.sports import GameStatus, SportsGamePlay, SportsTeam
from app.feed.schemas import SpoilerPolicy
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


def _game() -> SimpleNamespace:
    home = _team(team_id=1, league_id=1, name="NHL Home", abbreviation="HOM")
    away = _team(team_id=2, league_id=1, name="NHL Away", abbreviation="AWY")
    return SimpleNamespace(
        id=91,
        league=SimpleNamespace(code="NHL"),
        home_team=home,
        away_team=away,
        plays=[],
        status=GameStatus.final.value,
        last_pbp_at=None,
        last_ingested_at=None,
    )


def _play(
    *,
    game_id: int,
    play_index: int,
    period: int,
    clock: str,
    play_type: str,
    team: SportsTeam,
    player_name: str,
    description: str,
    home_score: int | None,
    away_score: int | None,
    situation_code: str | None = "1551",
    details: dict | None = None,
) -> SportsGamePlay:
    raw_data = {
        "event_id": play_index,
        "time_remaining": clock,
        "time_in_period": "00:00",
        "period_type": "REG",
        "type_desc_key": play_type.replace("_", "-"),
        "details": {
            "eventOwnerTeamId": team.id,
            **(details or {}),
        },
    }
    if situation_code is not None:
        raw_data["situation_code"] = situation_code
    return SportsGamePlay(
        game_id=game_id,
        quarter=period,
        game_clock=clock,
        play_index=play_index,
        play_type=play_type,
        team=team,
        player_name=player_name,
        description=description,
        home_score=home_score,
        away_score=away_score,
        raw_data=raw_data,
    )


def _cards(
    game: SimpleNamespace,
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.pre_reveal,
) -> list[dict]:
    return build_card_feed_from_game(
        game, spoiler_policy
    ).model_dump(by_alias=True, mode="json", exclude_none=True)["cards"]


def test_nhl_card_context_promotes_power_play_goal_assists_and_score_impact() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=101,
            period=2,
            clock="11:42",
            play_type="goal",
            team=game.home_team,
            player_name="Casey Shooter",
            description="Goal by Casey Shooter (snap)",
            home_score=1,
            away_score=0,
            situation_code="1451",
            details={
                "shotType": "snap",
                "scoringPlayerId": 10,
                "assist1PlayerId": 11,
                "assist2PlayerId": 12,
                "homeScore": 1,
                "awayScore": 0,
            },
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert card["scoreBefore"] == {"home": 0, "away": 0}
    assert card["scoreChange"] == {"home": 1, "away": 0}
    assert card["impact"] == "scoring"
    assert context["strength"]["state"] == "power_play"
    assert context["strength"]["skaters"] == {"away": 4, "home": 5}
    assert context["event"]["shotType"] == "snap"
    assert context["event"]["assistPlayerIds"] == ["11", "12"]
    assert context["flags"]["isPowerPlayGoal"] is True
    assert "power play" in card["situation"]["summary"]


def test_nhl_card_context_promotes_penalty_duration_without_strength_guess() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=201,
            period=1,
            clock="14:36",
            play_type="penalty",
            team=game.away_team,
            player_name="Morgan Defender",
            description="Penalty on Morgan Defender: hooking (2 min)",
            home_score=0,
            away_score=0,
            situation_code=None,
            details={
                "descKey": "hooking",
                "duration": 2,
                "committedByPlayerId": 20,
                "drawnByPlayerId": 21,
            },
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert context["event"]["penaltyType"] == "hooking"
    assert context["event"]["penaltyDurationMinutes"] == 2
    assert "strength" not in context
    assert context["flags"]["isPowerPlay"] is False
    assert "power play" not in card["situation"]["summary"]


def test_nhl_card_context_promotes_save_context_from_shot_on_goal() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=251,
            period=2,
            clock="06:03",
            play_type="shot_on_goal",
            team=game.away_team,
            player_name="Point Shooter",
            description="Point Shooter shot on goal.",
            home_score=0,
            away_score=0,
            details={
                "shotType": "slap",
                "shootingPlayerId": 31,
                "goalieInNetId": 40,
            },
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert context["event"]["shotType"] == "slap"
    assert context["event"]["isSaveContext"] is True
    assert context["score"]["impact"] == "none"
    assert "save chance" in card["situation"]["summary"]


def test_nhl_card_context_flags_late_tying_and_lead_change_goals() -> None:
    tying_game = _game()
    tying_game.plays = [
        _play(
            game_id=tying_game.id,
            play_index=301,
            period=1,
            clock="10:00",
            play_type="goal",
            team=tying_game.away_team,
            player_name="Away Scorer",
            description="Away Scorer scores.",
            home_score=0,
            away_score=1,
        ),
        _play(
            game_id=tying_game.id,
            play_index=302,
            period=3,
            clock="02:14",
            play_type="goal",
            team=tying_game.home_team,
            player_name="Tie Maker",
            description="Tie Maker scores late.",
            home_score=1,
            away_score=1,
            details={"shotType": "wrist"},
        ),
    ]

    tying_card = _cards(tying_game, SpoilerPolicy.revealed)[1]
    tying_context = tying_card["situation"]["raw"]

    assert tying_card["impact"] == "tying"
    assert tying_context["flags"]["isTyingGoal"] is True
    assert tying_context["flags"]["isLateGame"] is True
    assert "late close game" in tying_card["situation"]["summary"]

    lead_change_game = _game()
    lead_change_game.plays = [
        _play(
            game_id=lead_change_game.id,
            play_index=401,
            period=2,
            clock="08:00",
            play_type="goal",
            team=lead_change_game.away_team,
            player_name="Away Scorer",
            description="Away Scorer scores.",
            home_score=1,
            away_score=2,
        ),
        _play(
            game_id=lead_change_game.id,
            play_index=402,
            period=3,
            clock="04:01",
            play_type="goal",
            team=lead_change_game.home_team,
            player_name="Lead Changer",
            description="Lead Changer scores twice in one play.",
            home_score=3,
            away_score=2,
        ),
    ]

    lead_change_card = _cards(lead_change_game, SpoilerPolicy.revealed)[1]
    lead_change_context = lead_change_card["situation"]["raw"]

    assert lead_change_card["impact"] == "lead_change"
    assert lead_change_context["flags"]["isLeadChange"] is True
    assert lead_change_context["score"]["impact"] == "lead_change"


def test_nhl_card_context_flags_goalie_pulled_and_empty_net() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=501,
            period=3,
            clock="00:48",
            play_type="goal",
            team=game.home_team,
            player_name="Finisher",
            description="Finisher scores into an empty net.",
            home_score=3,
            away_score=1,
            situation_code="0651",
            details={
                "shotType": "backhand",
                "homeScore": 3,
                "awayScore": 1,
            },
        )
    ]

    card = _cards(game, SpoilerPolicy.revealed)[0]
    context = card["situation"]["raw"]

    assert card["impact"] == "empty_net_goal"
    assert context["strength"]["goaliePulled"] is True
    assert context["strength"]["goaliePulledSides"] == ["away"]
    assert context["event"]["emptyNet"] is True
    assert context["flags"]["isGoaliePulled"] is True
    assert context["flags"]["isEmptyNet"] is True
