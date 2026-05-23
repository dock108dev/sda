"""Tests for backend-owned play importance contract enrichment."""

import pytest

from app.routers.sports.schemas.common import PlayEntry, _score_obj
from app.services.play_importance import (
    DetailContractError,
    display_type_for,
    enrich_play_importance,
    validate_detail_contract,
)
from app.services.play_tiers import classify_all_tiers, enrich_play_entries


def _play(
    play_index: int,
    *,
    quarter: int = 1,
    game_clock: str | None = "10:00",
    play_type: str | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    period_label: str | None = None,
) -> PlayEntry:
    return PlayEntry(
        play_index=play_index,
        quarter=quarter,
        game_clock=game_clock,
        play_type=play_type,
        period_label=period_label or f"Q{quarter}",
        score=_score_obj(home_score, away_score),
    )


def _enrich(
    plays: list[PlayEntry],
    league_code: str,
    *,
    home_abbr: str = "HME",
    away_abbr: str = "AWY",
) -> list[PlayEntry]:
    tiers = classify_all_tiers(plays, league_code)
    for play, tier in zip(plays, tiers, strict=False):
        play.tier = tier
    enrich_play_entries(plays, league_code, home_abbr, away_abbr)
    enrich_play_importance(
        plays,
        league_code=league_code,
        home_abbr=home_abbr,
        away_abbr=away_abbr,
    )
    return plays


def test_display_type_maps_raw_enums_to_customer_labels() -> None:
    assert display_type_for("HOME_RUN") == "Home run"
    assert display_type_for("FIELD_OUT") == "Out"
    assert display_type_for("FORCE_OUT") == "Force out"
    assert display_type_for("unknown_backend_value") == "Unknown backend value"
    assert display_type_for(None) == "Other play"


def test_contract_enrichment_sets_required_fields_for_every_play() -> None:
    plays = _enrich(
        [
            _play(1, play_type="made_shot", home_score=2, away_score=0),
            _play(2, play_type="turnover", home_score=2, away_score=0),
        ],
        "NBA",
    )

    validate_detail_contract(plays)
    assert all(play.mode_eligibility and play.mode_eligibility.all for play in plays)
    assert all(play.importance for play in plays)
    assert all(play.display_type for play in plays)
    assert all(play.period_label for play in plays)


def test_contract_validation_fails_when_required_metadata_is_missing() -> None:
    with pytest.raises(DetailContractError):
        validate_detail_contract([_play(1, play_type="made_shot", home_score=2, away_score=0)])


def test_nba_ordinary_early_scoring_is_standard_not_important() -> None:
    plays = _enrich(
        [
            _play(1, quarter=1, play_type="2pt", home_score=2, away_score=0),
            _play(2, quarter=1, play_type="defensive_rebound", home_score=2, away_score=0),
        ],
        "NBA",
    )

    scoring_play = plays[0]
    assert scoring_play.importance is not None
    assert scoring_play.mode_eligibility is not None
    assert scoring_play.importance.is_scoring_play is True
    assert scoring_play.importance.level == "secondary"
    assert scoring_play.mode_eligibility.important is False
    assert scoring_play.mode_eligibility.standard is True


def test_nba_late_close_turnover_is_important_without_scoring() -> None:
    plays = _enrich(
        [
            _play(1, quarter=4, play_type="made_shot", home_score=100, away_score=100),
            _play(2, quarter=4, play_type="turnover", home_score=100, away_score=100),
            _play(3, quarter=4, play_type="defensive_rebound", home_score=100, away_score=100),
        ],
        "NBA",
    )

    turnover = plays[1]
    assert turnover.importance is not None
    assert turnover.mode_eligibility is not None
    assert turnover.importance.is_scoring_play is False
    assert turnover.importance.level == "primary"
    assert turnover.mode_eligibility.important is True


def test_mlb_threat_ending_double_play_is_important_without_scoring() -> None:
    plays = _enrich(
        [
            _play(1, quarter=6, play_type="single", home_score=1, away_score=1, period_label="6th"),
            _play(2, quarter=6, play_type="double_play", home_score=1, away_score=1, period_label="6th"),
            _play(3, quarter=6, play_type="field_out", home_score=1, away_score=1, period_label="6th"),
        ],
        "MLB",
        home_abbr="PHI",
        away_abbr="CIN",
    )

    double_play = plays[1]
    assert double_play.importance is not None
    assert double_play.mode_eligibility is not None
    assert double_play.importance.is_scoring_play is False
    assert double_play.display_type == "Double play"
    assert double_play.importance.level == "primary"
    assert double_play.mode_eligibility.important is True


def test_scoring_play_includes_score_progression_display() -> None:
    plays = _enrich(
        [
            _play(1, quarter=3, play_type="home_run", home_score=1, away_score=2, period_label="Top 3rd"),
            _play(2, quarter=3, play_type="field_out", home_score=1, away_score=2, period_label="Top 3rd"),
        ],
        "MLB",
        home_abbr="PHI",
        away_abbr="CIN",
    )

    assert plays[0].score_changed is True
    assert plays[0].score_after == plays[0].score
    assert plays[0].score_display == "CIN 2 · PHI 1"
