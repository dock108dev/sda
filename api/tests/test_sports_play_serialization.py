from app.db.sports import SportsGamePlay, SportsTeam
from app.routers.sports.common import serialize_play_entry


def test_mlb_play_serializer_exposes_situational_context_for_consumer() -> None:
    team = SportsTeam(
        id=7,
        league_id=1,
        name="Milwaukee Brewers",
        short_name="Brewers",
        abbreviation="MIL",
    )
    play = SportsGamePlay(
        game_id=42,
        quarter=4,
        game_clock=None,
        play_index=28,
        play_type="home_run",
        team=team,
        player_name="Jake Bauers",
        description="Jake Bauers homers on a fly ball to left field.",
        home_score=0,
        away_score=2,
        raw_data={
            "situationBefore": {
                "outs": 1,
                "baseState": {"first": True, "second": False, "third": False},
                "batterName": "Jake Bauers",
                "pitcherName": "Tatsuro Imai",
            },
            "outsAfter": 1,
            "baseStateAfter": {"first": False, "second": False, "third": False},
            "inning": 4,
            "inningHalf": "top",
            "balls": 0,
            "strikes": 0,
            "battingTeamAbbr": "MIL",
            "fieldingTeamAbbr": "HOU",
            "eventType": "home_run",
            "isScoringPlay": True,
            "rawDescription": "Jake Bauers homers (9) on a fly ball to left field.",
        },
    )

    entry = serialize_play_entry(play, "MLB")
    payload = entry.model_dump(by_alias=True, exclude_none=True)

    assert payload["situationBefore"]["display"]["headline"] == "Top 4, 1 out, 1st"
    assert payload["situationBefore"]["sportState"]["baseball"] == {
        "inning": 4,
        "half": "top",
        "outs": 1,
        "bases": {"first": True, "second": False, "third": False},
        "baseState": "1st",
        "battingTeamAbbreviation": "MIL",
        "fieldingTeamAbbreviation": "HOU",
        "batterName": "Jake Bauers",
        "pitcherName": "Tatsuro Imai",
    }
    assert payload["situationAfter"]["display"]["headline"] == "Top 4, 1 out, Bases empty"
    assert payload["metadata"] == {"eventType": "home_run", "isScoringPlay": True}
    assert payload["sportMetadata"]["playIndex"] == 28
    assert payload["sportMetadata"]["sport"] == "mlb"
    assert payload["rawFeedText"] == "Jake Bauers homers (9) on a fly ball to left field."
    assert payload["rawFeedSource"] == "upstream"
