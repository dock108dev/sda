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


def _game(league: str = "NFL") -> SimpleNamespace:
    home = _team(team_id=1, league_id=1, name=f"{league} Home", abbreviation="HOM")
    away = _team(team_id=2, league_id=1, name=f"{league} Away", abbreviation="AWY")
    return SimpleNamespace(
        id=71,
        league=SimpleNamespace(code=league),
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
    description: str,
    home_score: int,
    away_score: int,
    raw_data: dict | None = None,
) -> SportsGamePlay:
    return SportsGamePlay(
        game_id=game_id,
        quarter=period,
        game_clock=clock,
        play_index=play_index,
        play_type=play_type,
        team=team,
        player_name=None,
        description=description,
        home_score=home_score,
        away_score=away_score,
        raw_data=raw_data or {},
    )


def _cards(game: SimpleNamespace) -> list[dict]:
    return build_card_feed_from_game(
        game, SpoilerPolicy.pre_reveal
    ).model_dump(by_alias=True, mode="json", exclude_none=True)["cards"]


def _raw(
    *,
    play_id: str,
    down: int,
    distance: int,
    yard_line: int,
    yards: int,
    scoring: bool = False,
    play_type_text: str = "Rush",
) -> dict:
    return {
        "espn_play_id": play_id,
        "play_type_id": "5",
        "play_type_text": play_type_text,
        "scoring_play": scoring,
        "yards": yards,
        "start_down": down,
        "start_distance": distance,
        "start_yard_line": yard_line,
    }


def test_football_card_context_flags_fourth_down_conversion_and_stop() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=401,
            period=1,
            clock="11:20",
            play_type="RUSH",
            team=game.home_team,
            description="HOM rushes for 4 yards on fourth down.",
            home_score=0,
            away_score=0,
            raw_data=_raw(
                play_id="espn-401",
                down=4,
                distance=2,
                yard_line=58,
                yards=4,
                play_type_text="Rush",
            ),
        ),
        _play(
            game_id=game.id,
            play_index=402,
            period=1,
            clock="06:20",
            play_type="PASS_INCOMPLETION",
            team=game.away_team,
            description="AWY pass incomplete on fourth down.",
            home_score=0,
            away_score=0,
            raw_data=_raw(
                play_id="espn-402",
                down=4,
                distance=3,
                yard_line=61,
                yards=0,
                play_type_text="Pass Incompletion",
            ),
        ),
    ]

    conversion, stop = _cards(game)
    conversion_context = conversion["situation"]["raw"]
    stop_context = stop["situation"]["raw"]

    assert conversion["sourcePlayId"] == "espn-401"
    assert conversion["impact"] == "fourth_down_conversion"
    assert conversion_context["drive"]["downDistance"] == "4th & 2"
    assert conversion_context["flags"]["isFourthDownConversion"] is True
    assert stop["impact"] == "fourth_down_stop"
    assert stop_context["flags"]["isFourthDownStop"] is True
    assert stop_context["drive"]["fieldPosition"]["label"] == "Opp 39"


def test_football_card_context_promotes_red_zone_scoring_play() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=501,
            period=2,
            clock="04:15",
            play_type="TOUCHDOWN",
            team=game.home_team,
            description="HOM scores from the red zone.",
            home_score=7,
            away_score=0,
            raw_data=_raw(
                play_id="espn-501",
                down=2,
                distance=6,
                yard_line=82,
                yards=18,
                scoring=True,
                play_type_text="Passing Touchdown",
            ),
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert card["scoreBefore"] == {"home": 0, "away": 0}
    assert card["scoreChange"] == {"home": 7, "away": 0}
    assert card["impact"] == "scoring"
    assert context["drive"]["fieldPosition"]["label"] == "Opp 18"
    assert context["drive"]["fieldPosition"]["isRedZone"] is True
    assert context["result"]["espnPlayId"] == "espn-501"
    assert context["flags"]["isRedZone"] is True
    assert context["flags"]["isScoringPlay"] is True


def test_football_card_context_flags_turnover_from_play_type_text() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=601,
            period=3,
            clock="09:48",
            play_type="INTERCEPTION",
            team=game.away_team,
            description="AWY intercepts the pass.",
            home_score=0,
            away_score=0,
            raw_data=_raw(
                play_id="espn-601",
                down=2,
                distance=8,
                yard_line=47,
                yards=0,
                play_type_text="Interception",
            ),
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert card["impact"] == "turnover"
    assert context["result"]["family"] == "turnover"
    assert context["flags"]["isTurnover"] is True


def test_football_card_context_flags_explosive_play() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=701,
            period=3,
            clock="05:12",
            play_type="RUSH",
            team=game.home_team,
            description="HOM rushes for 12 yards.",
            home_score=0,
            away_score=0,
            raw_data=_raw(
                play_id="espn-701",
                down=1,
                distance=10,
                yard_line=35,
                yards=12,
                play_type_text="Rush",
            ),
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert card["impact"] == "explosive_play"
    assert context["result"]["yards"] == 12
    assert context["flags"]["isExplosivePlay"] is True


def test_football_card_context_flags_two_minute_situation() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=801,
            period=2,
            clock="01:59",
            play_type="PASS",
            team=game.away_team,
            description="AWY completes a short pass before halftime.",
            home_score=0,
            away_score=0,
            raw_data=_raw(
                play_id="espn-801",
                down=1,
                distance=10,
                yard_line=44,
                yards=5,
                play_type_text="Pass",
            ),
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert card["impact"] == "two_minute"
    assert context["clock"]["secondsRemaining"] == 119
    assert context["flags"]["isTwoMinuteSituation"] is True
    assert "two minute" in card["situation"]["summary"]


def test_football_card_context_keeps_routine_first_down_play_low_impact() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=901,
            period=1,
            clock="12:41",
            play_type="RUSH",
            team=game.home_team,
            description="HOM rushes for 3 yards.",
            home_score=0,
            away_score=0,
            raw_data=_raw(
                play_id="espn-901",
                down=1,
                distance=10,
                yard_line=25,
                yards=3,
                play_type_text="Rush",
            ),
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert card["impact"] == "none"
    assert context["score"]["impact"] == "none"
    assert context["drive"]["downDistance"] == "1st & 10"
    assert context["drive"]["fieldPosition"]["label"] == "Own 25"
    assert context["flags"]["isRedZone"] is False
    assert context["flags"]["isFourthDown"] is False


def test_football_card_context_gates_ncaaf_drive_fields_to_available_source_data() -> None:
    game = _game("NCAAF")
    game.plays = [
        _play(
            game_id=game.id,
            play_index=1001,
            period=1,
            clock="12:00",
            play_type="RUSH",
            team=game.home_team,
            description="HOM rushes on first down.",
            home_score=0,
            away_score=0,
            raw_data={},
        )
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert context["sport"] == "football"
    assert context["league"] == "NCAAF"
    assert "drive" not in context
    assert "result" in context
    assert card["sourcePlayId"] == "1001"
