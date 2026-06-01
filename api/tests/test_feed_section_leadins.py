from __future__ import annotations

from app.feed.schemas import CardPeriod, CardSituation, CardTeam, NarrativeCard, ScoreChange
from app.feed.section_leadins import build_section_lead_ins
from app.routers.sports.schemas.common import PlayImportance, PlayModeEligibility


def _card(play_index: int, raw: dict) -> NarrativeCard:
    return NarrativeCard(
        id=f"7:{play_index}",
        gameId=7,
        sourcePlayId=str(play_index),
        playIndex=play_index,
        sport="basketball",
        league="NBA",
        tier=2,
        contentDepth="standard",
        modeEligibility=PlayModeEligibility(important=False, standard=True, all=True),
        importance=PlayImportance(level="secondary", reasons=[], isKeyMoment=False),
        visualImportance="medium",
        period=CardPeriod(ordinal=1, label="Q1", type="REG"),
        displayTime="Q1 08:00",
        clock="08:00",
        team=CardTeam(abbreviation="HOM", name="Home", side="home"),
        scoreBefore=None,
        scoreChange=ScoreChange(home=0, away=0),
        scoreAfter=None,
        situation=CardSituation(summary="Set offense", raw=raw),
        leadIn="Q1 08:00 - HOM",
        stageSetting="Q1 08:00 - HOM",
        headline="Backend headline",
        description="Backend detail",
        impact=None,
        tags=[],
        spoilerLevel="none",
    )


def test_section_lead_in_uses_safe_generated_copy_when_present() -> None:
    sections = build_section_lead_ins(
        [_card(1, {"narrative": {"sectionLeadIn": "The first quarter starts settled."}})]
    )

    assert sections[0].lead_in == "The first quarter starts settled."
    assert sections[0].source == "generated"


def test_section_lead_in_falls_back_when_generated_copy_leaks_outcome() -> None:
    sections = build_section_lead_ins(
        [_card(1, {"narrative": {"sectionLeadIn": "Later, the winner sealed the 99-98 final."}})]
    )

    assert sections[0].lead_in == "First quarter opens the feed."
    assert sections[0].source == "fallback"
