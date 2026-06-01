from __future__ import annotations

from types import SimpleNamespace

from app.db.sports import GameStatus, SportsGamePlay, SportsTeam
from app.feed.basketball_context import build_basketball_card_contexts
from app.feed.schemas import SpoilerPolicy
from app.feed.service import build_card_feed_from_game
from app.routers.sports.schemas.common import PlayEntry, ScoreObject


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


def _game(league: str = "NBA") -> SimpleNamespace:
    home = _team(team_id=1, league_id=1, name=f"{league} Home", abbreviation="HOM")
    away = _team(team_id=2, league_id=1, name=f"{league} Away", abbreviation="AWY")
    return SimpleNamespace(
        id=101,
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
    player_name: str,
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
        player_name=player_name,
        description=description,
        home_score=home_score,
        away_score=away_score,
        raw_data=raw_data or {},
    )


def _cards(
    game: SimpleNamespace,
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.pre_reveal,
) -> list[dict]:
    return build_card_feed_from_game(
        game, spoiler_policy
    ).model_dump(by_alias=True, mode="json", exclude_none=True)["cards"]


def test_basketball_card_context_promotes_scoring_run_from_configured_threshold() -> None:
    game = _game("NBA")
    game.plays = [
        _play(
            game_id=game.id,
            play_index=1,
            period=2,
            clock="08:40",
            play_type="layup",
            team=game.home_team,
            player_name="Run Starter",
            description="Run Starter makes a layup.",
            home_score=2,
            away_score=0,
        ),
        _play(
            game_id=game.id,
            play_index=2,
            period=2,
            clock="08:01",
            play_type="3pt_made",
            team=game.home_team,
            player_name="Arc Shooter",
            description="Arc Shooter makes a three.",
            home_score=5,
            away_score=0,
        ),
        _play(
            game_id=game.id,
            play_index=3,
            period=2,
            clock="07:31",
            play_type="layup",
            team=game.home_team,
            player_name="Run Extender",
            description="Run Extender makes a layup.",
            home_score=7,
            away_score=0,
        ),
        _play(
            game_id=game.id,
            play_index=4,
            period=2,
            clock="07:05",
            play_type="dunk",
            team=game.home_team,
            player_name="Run Finisher",
            description="Run Finisher dunks.",
            home_score=9,
            away_score=0,
        ),
    ]

    card = _cards(game, SpoilerPolicy.revealed)[-1]
    context = card["situation"]["raw"]

    assert card["impact"] == "scoring_run"
    assert context["run"]["label"] == "9-0 home run"
    assert context["run"]["thresholdPoints"] == 8
    assert context["flags"]["isRunEnding"] is True
    assert "9-0 home run" in card["situation"]["summary"]

    pre_reveal_card = _cards(game, SpoilerPolicy.pre_reveal)[-1]
    assert pre_reveal_card["stageSetting"] != pre_reveal_card["leadIn"]
    assert pre_reveal_card["stageSetting"].startswith("Q2 07:05")
    assert "run" not in pre_reveal_card["stageSetting"].lower()


def test_basketball_card_context_flags_lead_change_and_tying_play() -> None:
    lead_change_game = _game("NBA")
    lead_change_game.plays = [
        _play(
            game_id=lead_change_game.id,
            play_index=1,
            period=3,
            clock="06:00",
            play_type="made_shot",
            team=lead_change_game.away_team,
            player_name="Away Builder",
            description="Away Builder sets the score.",
            home_score=87,
            away_score=88,
        ),
        _play(
            game_id=lead_change_game.id,
            play_index=2,
            period=3,
            clock="05:42",
            play_type="3pt_made",
            team=lead_change_game.home_team,
            player_name="Lead Flipper",
            description="Lead Flipper makes a three.",
            home_score=90,
            away_score=88,
        ),
    ]

    lead_card = _cards(lead_change_game, SpoilerPolicy.revealed)[1]
    lead_context = lead_card["situation"]["raw"]
    assert lead_card["impact"] == "lead_change"
    assert lead_context["lead"]["leaderBefore"] == "away"
    assert lead_context["lead"]["leaderAfter"] == "home"
    assert lead_context["lead"]["isLeadChange"] is True

    tying_game = _game("NBA")
    tying_game.plays = [
        _play(
            game_id=tying_game.id,
            play_index=1,
            period=4,
            clock="09:00",
            play_type="made_shot",
            team=tying_game.away_team,
            player_name="Away Scorer",
            description="Away Scorer scores.",
            home_score=47,
            away_score=50,
        ),
        _play(
            game_id=tying_game.id,
            play_index=2,
            period=4,
            clock="08:21",
            play_type="3pt_made",
            team=tying_game.home_team,
            player_name="Tie Maker",
            description="Tie Maker makes a three.",
            home_score=50,
            away_score=50,
        ),
    ]

    tying_card = _cards(tying_game, SpoilerPolicy.revealed)[1]
    tying_context = tying_card["situation"]["raw"]
    assert tying_card["impact"] == "tying"
    assert tying_context["lead"]["isTyingPlay"] is True
    assert tying_context["flags"]["isTyingPlay"] is True


def test_basketball_card_context_flags_clutch_time_score_and_free_throw() -> None:
    game = _game("NBA")
    game.plays = [
        _play(
            game_id=game.id,
            play_index=1,
            period=4,
            clock="05:20",
            play_type="made_shot",
            team=game.away_team,
            player_name="Away Guard",
            description="Away Guard scores.",
            home_score=98,
            away_score=100,
        ),
        _play(
            game_id=game.id,
            play_index=2,
            period=4,
            clock="04:59",
            play_type="free_throw",
            team=game.home_team,
            player_name="Clutch Shooter",
            description="Clutch Shooter makes free throw 1 of 2.",
            home_score=99,
            away_score=100,
        ),
    ]

    card = _cards(game, SpoilerPolicy.revealed)[1]
    context = card["situation"]["raw"]

    assert card["impact"] == "clutch_score"
    assert context["clutch"]["isClutch"] is True
    assert context["clutch"]["reason"] == "final_5_close"
    assert context["result"]["freeThrow"] == {"made": True}
    assert context["score"]["impact"] == "clutch_score"


def test_basketball_card_context_promotes_three_point_without_text_inferred_and_one() -> None:
    game = _game("NBA")
    game.plays = [
        _play(
            game_id=game.id,
            play_index=1,
            period=1,
            clock="10:15",
            play_type="3pt_made",
            team=game.home_team,
            player_name="Deep Shooter",
            description="Deep Shooter makes a three and draws the foul.",
            home_score=3,
            away_score=0,
        )
    ]

    card = _cards(game)[0]
    result = card["situation"]["raw"]["result"]

    assert card["scoreChange"] == {"home": 3, "away": 0}
    assert result["threePoint"] == {"made": True, "points": 3}
    assert "andOne" not in result
    assert "freeThrow" not in result
    assert "timeout" not in result


def test_basketball_card_context_includes_explicit_and_one_metadata() -> None:
    game = _game("NBA")
    play = PlayEntry(
        playIndex=1,
        quarter=1,
        gameClock="10:15",
        periodLabel="Q1",
        timeLabel="Q1 10:15",
        playType="3pt_made",
        displayType="3-pointer",
        teamAbbreviation="HOM",
        playerName="Deep Shooter",
        description="Deep Shooter makes a three and draws the foul.",
        score=ScoreObject(home=3, away=0),
        scoreBefore=ScoreObject(home=0, away=0),
        scoreAfter=ScoreObject(home=3, away=0),
        scoreChanged=True,
        sportMetadata={"andOne": True},
    )

    context = build_basketball_card_contexts(game, [play])[1].raw

    assert context["result"]["andOne"] is True


def test_basketball_card_context_preserves_ncaab_half_labels_and_routine_output() -> None:
    game = _game("NCAAB")
    game.plays = [
        _play(
            game_id=game.id,
            play_index=1,
            period=2,
            clock="12:30",
            play_type="made_shot",
            team=game.home_team,
            player_name="Setup Scorer",
            description="Setup Scorer makes a jumper.",
            home_score=44,
            away_score=41,
        ),
        _play(
            game_id=game.id,
            play_index=2,
            period=2,
            clock="12:11",
            play_type="defensive_rebound",
            team=game.away_team,
            player_name="Board Getter",
            description="Board Getter defensive rebound.",
            home_score=44,
            away_score=41,
        )
    ]

    card = _cards(game)[1]
    context = card["situation"]["raw"]

    assert card["period"]["label"] == "H2"
    assert context["period"]["unit"] == "half"
    assert context["result"]["family"] == "rebound"
    assert context["score"]["impact"] == "none"
    assert context["flags"]["isScoringPlay"] is False
    assert "threePoint" not in context["result"]
    assert "freeThrow" not in context["result"]
