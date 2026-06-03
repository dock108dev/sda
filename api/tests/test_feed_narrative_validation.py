from __future__ import annotations

from app.feed.narrative_validation import (
    NarrativeValidationContext,
    validate_card_text,
)


def _context(**overrides: object) -> NarrativeValidationContext:
    values = {
        "home_team": "Harbor Herons",
        "away_team": "Mesa Larks",
        "home_abbrev": "HH",
        "away_abbrev": "ML",
        "home_aliases": frozenset({"Harbor Herons", "Herons", "HH"}),
        "away_aliases": frozenset({"Mesa Larks", "Larks", "ML"}),
        "current_play_index": 20,
        "allow_final_score": False,
        "score_before": (2, 1),
        "score_after": (3, 1),
        "score_change": (1, 0),
        "final_score": (5, 2),
        "allowed_scores": frozenset({(0, 0), (2, 1), (3, 1)}),
        "allowed_player_names": frozenset({"Rafi Nolen"}),
        "future_player_names": frozenset({"Dax Moreno"}),
        "scoring_side": "home",
    }
    values.update(overrides)
    return NarrativeValidationContext(**values)


def _codes(text: str, context: NarrativeValidationContext | None = None) -> list[str]:
    findings = validate_card_text(text=text, field="headline", context=context or _context())
    return [finding.code for finding in findings]


def test_future_winner_final_score_and_future_language_fall_back() -> None:
    findings = validate_card_text(
        text="The Harbor Herons would eventually seal the 5-2 win.",
        field="headline",
        context=_context(),
    )

    assert {
        "narrative_future_outcome_phrase",
        "narrative_final_score_leak",
        "narrative_winner_leak",
    } <= {finding.code for finding in findings}
    assert {finding.action for finding in findings} == {"fallback_text"}


def test_future_phrase_matching_does_not_trigger_inside_player_names() -> None:
    assert "narrative_future_outcome_phrase" not in _codes(
        "Austin Slater doubles on a line drive to left fielder Josh Lowe.",
        _context(future_player_names=frozenset()),
    )


def test_score_claims_require_allowed_pairs_and_team_order() -> None:
    final_score_context = _context(
        allow_final_score=True,
        score_after=(5, 2),
        allowed_scores=frozenset({(5, 2)}),
        final_score=(5, 2),
    )

    assert "narrative_score_not_allowed" in _codes(
        "The Harbor Herons led 7-2 after the swing.",
        final_score_context,
    )
    assert "narrative_score_team_order_mismatch" in _codes(
        "The Harbor Herons beat the Mesa Larks 2-5.",
        final_score_context,
    )
    assert "narrative_margin_mismatch" in _codes(
        "The Harbor Herons moved ahead by three.",
        _context(allowed_scores=frozenset({(2, 1), (3, 1)})),
    )


def test_team_role_scoring_side_and_future_player_mentions_are_blockers() -> None:
    codes = set(
        _codes(
            "The Mesa Larks fed off the home crowd. Mesa Larks scores again before Dax Moreno appears.",
            _context(),
        )
    )

    assert "narrative_home_away_role_mismatch" in codes
    assert "narrative_future_player_mention" in codes
    assert "narrative_team_score_mismatch" in codes
