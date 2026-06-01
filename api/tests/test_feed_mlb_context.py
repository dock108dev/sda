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
    home = _team(team_id=1, league_id=1, name="MLB Home", abbreviation="HOM")
    away = _team(team_id=2, league_id=1, name="MLB Away", abbreviation="AWY")
    return SimpleNamespace(
        id=42,
        league=SimpleNamespace(code="MLB"),
        home_team=home,
        away_team=away,
        plays=[],
        status=GameStatus.final.value,
        last_pbp_at=None,
        last_ingested_at=None,
    )


def _runner(
    *,
    name: str,
    origin: str | None,
    end: str | None,
    is_out: bool = False,
) -> dict:
    return {
        "movement": {"originBase": origin, "end": end, "isOut": is_out},
        "details": {"runner": {"fullName": name}},
    }


def _play(
    *,
    game_id: int,
    play_index: int,
    inning: int,
    is_top: bool,
    play_type: str,
    team: SportsTeam,
    player_name: str,
    description: str,
    home_score: int,
    away_score: int,
    runners: list[dict] | None = None,
    outs_after: int | None = None,
    score_before: tuple[int, int] | None = None,
) -> SportsGamePlay:
    raw_data = {
        "inning": inning,
        "half_inning": "top" if is_top else "bottom",
        "is_top_inning": is_top,
        "batter": {"id": play_index, "name": player_name},
        "pitcher": {"id": 900 + play_index, "name": "Casey Pitcher"},
        "count": {"balls": 2, "strikes": 1},
        "runners": runners or [],
    }
    if outs_after is not None:
        raw_data["outsAfter"] = outs_after
    if score_before is not None:
        raw_data["scoreBefore"] = {"home": score_before[0], "away": score_before[1]}
    return SportsGamePlay(
        game_id=game_id,
        quarter=inning,
        game_clock=None,
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


def test_mlb_card_context_promotes_base_out_score_and_matchup() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=801,
            inning=8,
            is_top=True,
            play_type="double",
            team=game.away_team,
            player_name="Tie Hitter",
            description="Tie Hitter doubles to right. Two runs score.",
            home_score=3,
            away_score=3,
            score_before=(3, 1),
            runners=[
                _runner(name="Fast Runner", origin="1B", end="home"),
                _runner(name="Lead Runner", origin="2B", end="home"),
                _runner(name="Tie Hitter", origin=None, end="2B"),
            ],
        )
    ]

    card = _cards(game, SpoilerPolicy.revealed)[0]
    context = card["situation"]["raw"]

    assert card["scoreBefore"] == {"home": 3, "away": 1}
    assert card["scoreChange"] == {"home": 0, "away": 2}
    assert card["scoreAfter"] == {"home": 3, "away": 3}
    assert context["period"] == {"ordinal": 8, "phase": "top", "label": "Top 8"}
    assert context["baseOut"]["outsBefore"] == 0
    assert context["baseOut"]["basesBefore"] == {
        "first": True,
        "second": True,
        "third": False,
    }
    assert context["baseOut"]["runnerNamesBefore"] == {
        "first": "F RUNNER",
        "second": "L RUNNER",
    }
    assert context["matchup"] == {
        "batterName": "Tie Hitter",
        "pitcherName": "Casey Pitcher",
        "count": {"balls": 2, "strikes": 1},
    }
    assert context["score"]["impact"] == "tying"


def test_mlb_card_context_flags_tying_go_ahead_and_lead_change() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=701,
            inning=7,
            is_top=True,
            play_type="single",
            team=game.away_team,
            player_name="Tie Runner",
            description="Tie Runner singles. One run scores.",
            home_score=2,
            away_score=2,
            score_before=(2, 1),
            runners=[_runner(name="Tie Runner", origin=None, end="1B")],
        ),
        _play(
            game_id=game.id,
            play_index=702,
            inning=7,
            is_top=False,
            play_type="home_run",
            team=game.home_team,
            player_name="Go Ahead",
            description="Go Ahead homers.",
            home_score=3,
            away_score=2,
            runners=[_runner(name="Go Ahead", origin=None, end="home")],
        ),
        _play(
            game_id=game.id,
            play_index=901,
            inning=9,
            is_top=True,
            play_type="home_run",
            team=game.away_team,
            player_name="Lead Flip",
            description="Lead Flip homers. Two runs score.",
            home_score=3,
            away_score=4,
            runners=[
                _runner(name="Late Runner", origin="1B", end="home"),
                _runner(name="Lead Flip", origin=None, end="home"),
            ],
        ),
    ]

    cards = _cards(game, SpoilerPolicy.revealed)
    impacts = [card["situation"]["raw"]["score"]["impact"] for card in cards]
    flags = [card["situation"]["raw"]["flags"] for card in cards]

    assert impacts == ["tying", "go_ahead", "lead_change"]
    assert flags[0]["isTyingPlay"] is True
    assert flags[1]["isGoAhead"] is True
    assert flags[2]["isLeadChange"] is True


def test_mlb_card_context_exposes_stranded_runners_and_routine_output() -> None:
    game = _game()
    game.plays = [
        _play(
            game_id=game.id,
            play_index=501,
            inning=5,
            is_top=True,
            play_type="field_out",
            team=game.away_team,
            player_name="Routine Batter",
            description="Routine Batter flies out to center field.",
            home_score=0,
            away_score=0,
            outs_after=3,
            runners=[
                _runner(name="Runner One", origin="1B", end="1B"),
                _runner(name="Runner Two", origin="2B", end="2B"),
            ],
        ),
        _play(
            game_id=game.id,
            play_index=601,
            inning=6,
            is_top=True,
            play_type="field_out",
            team=game.away_team,
            player_name="Next Batter",
            description="Next Batter grounds out.",
            home_score=0,
            away_score=0,
            outs_after=1,
        ),
    ]

    card = _cards(game)[0]
    context = card["situation"]["raw"]

    assert card["modeEligibility"] == {"important": False, "standard": False, "all": True}
    assert card["contentDepth"] == "brief"
    assert context["flags"]["isInningEnding"] is True
    assert context["score"]["impact"] == "none"
    assert context["baseOut"]["outsAfter"] == 3
    assert context["baseOut"]["strandedRunners"] == ["R ONE", "R TWO"]
