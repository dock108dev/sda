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


def test_nhl_play_serializer_exposes_hockey_situational_context_for_consumer() -> None:
    team = SportsTeam(
        id=14,
        league_id=1,
        name="Tampa Bay Lightning",
        short_name="Lightning",
        abbreviation="TBL",
    )
    play = SportsGamePlay(
        game_id=42,
        quarter=3,
        game_clock="02:14",
        play_index=302,
        play_type="goal",
        team=team,
        player_name="Brayden Point",
        description="Goal by Brayden Point (wrist)",
        home_score=2,
        away_score=2,
        raw_data={
            "event_id": 302,
            "time_remaining": "02:14",
            "time_in_period": "17:46",
            "period_type": "REG",
            "situation_code": "1541",
            "type_code": 505,
            "type_desc_key": "goal",
            "details": {
                "eventOwnerTeamId": 14,
                "shotType": "wrist",
                "scoringPlayerId": 8478010,
                "assist1PlayerId": 8476453,
                "duration": None,
                "homeScore": 2,
                "awayScore": 2,
            },
        },
    )

    entry = serialize_play_entry(play, "NHL")
    payload = entry.model_dump(by_alias=True, exclude_none=True)

    hockey = payload["situationBefore"]["sportState"]["hockey"]
    assert payload["situationBefore"]["display"]["headline"] == "P3, P3 02:14, special teams"
    assert hockey["situationCode"] == "1541"
    assert hockey["strengthState"] == "special_teams"
    assert hockey["skaters"] == {"away": 5, "home": 4}
    assert hockey["goalies"] == {"away": 1, "home": 1}
    assert hockey["shotType"] == "wrist"
    assert hockey["assistPlayerIds"] == ["8476453"]
    assert payload["situationBefore"]["event"]["shotType"] == "wrist"
    assert payload["metadata"]["situationCode"] == "1541"
    assert payload["metadata"]["shotType"] == "wrist"
    assert payload["metadata"]["assistPlayerIds"] == ["8476453"]
    assert payload["sportMetadata"]["sport"] == "nhl"
