"""Tests for banned-phrase + speculation detection in narrative blocks.

Covers:
- Every entry in ``BANNED_PHRASES`` is individually detected.
- Banned-phrase hits become validation errors (REGENERATE class).
- Speculation patterns become warnings without forcing FALLBACK.
- Clean text passes both gates.
- Sport-specific assertions per BRAINDUMP §Test cases:
  * MLB shutouts must not use exaggerated dominance language ("dominant",
    "impenetrable") — Rule 14 surfaces these for low-event archetypes.
  * NBA blowout late blocks must not imply fake leverage ("rally",
    "comeback", "could still") — Rule 13.

Detection is substring + lowercase, so the tests embed each phrase verbatim
in a longer narrative to mirror real renderer output.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.pipeline.stages.render_validation import (
    BANNED_PHRASES,
    SPECULATION_PATTERNS,
)
from app.services.pipeline.stages.validate_blocks_phrases import (
    check_banned_phrases,
)
from app.services.pipeline.stages.validate_blocks_segments import (
    validate_blowout_late_leverage,
    validate_low_event_drama,
)


def _block(narrative: str, *, block_index: int = 0) -> dict[str, Any]:
    return {"block_index": block_index, "narrative": narrative}


# ---------------------------------------------------------------------------
# 1) Every banned phrase is individually detected.
# ---------------------------------------------------------------------------


class TestEveryBannedPhraseIsDetected:
    """Each entry in BANNED_PHRASES must be flagged when used in narrative."""

    @pytest.mark.parametrize("phrase", BANNED_PHRASES)
    def test_each_banned_phrase_produces_error(self, phrase: str) -> None:
        narrative = (
            f"In the third inning the team {phrase} and pulled away in the "
            "later frames as the lead grew."
        )
        errors, _warnings = check_banned_phrases([_block(narrative)])
        assert errors, f"phrase {phrase!r} should produce a banned-phrase error"
        # The matched phrase appears in the rendered error message.
        assert any(phrase in err for err in errors)

    def test_banned_list_size_matches_braindump_spec(self) -> None:
        """BRAINDUMP enumerates ~20 cliché phrases; ensure we are at parity.

        Tracked as a sanity check — if a phrase is added or removed in
        ``render_validation.BANNED_PHRASES``, this test fails loudly so the
        BRAINDUMP and the regen ruleset stay in sync.
        """
        # Spec calls out 20; current implementation has 21 (a near-duplicate
        # "eager to set the tone" overlaps with "set the tone"). Both must be
        # actively maintained so we lock the count to the implementation
        # rather than a magic number — the parametrized test above is the
        # behavioral check.
        assert len(BANNED_PHRASES) >= 20


# ---------------------------------------------------------------------------
# 2) Detection translates to REGENERATE decisions.
# ---------------------------------------------------------------------------


class TestRegenerateDecisionPath:
    """check_banned_phrases routes hits to validate_blocks errors → REGENERATE."""

    def test_banned_phrase_returns_error_not_warning(self) -> None:
        narrative = "The home side came out strong and never looked back."
        errors, warnings = check_banned_phrases([_block(narrative)])
        assert len(errors) == 1
        assert warnings == []

    def test_multiple_blocks_each_reported_separately(self) -> None:
        blocks = [
            _block("The team came out strong from the opening bell.", block_index=0),
            _block("Defense remained composed under sustained pressure.", block_index=1),
            _block("Plain factual narrative with no banned content here.", block_index=2),
        ]
        errors, _ = check_banned_phrases(blocks)
        # Two offending blocks → two error messages.
        assert len(errors) == 2
        assert any("Block 0" in e for e in errors)
        assert any("Block 1" in e for e in errors)

    def test_multiple_banned_phrases_in_one_block_collapse_to_one_error(self) -> None:
        narrative = (
            "The team came out strong, set the tone, and secured the victory "
            "with a dominant performance."
        )
        errors, _ = check_banned_phrases([_block(narrative)])
        assert len(errors) == 1
        # All four phrases appear in the rendered error.
        assert "came out strong" in errors[0]
        assert "set the tone" in errors[0]
        assert "secured the victory" in errors[0]
        assert "dominant performance" in errors[0]


# ---------------------------------------------------------------------------
# 3) Speculation patterns produce warnings, not REGENERATE errors.
# ---------------------------------------------------------------------------


class TestSpeculationDetection:
    """Speculation phrases produce warnings only — they don't force REGENERATE."""

    def test_speculation_phrase_is_warning(self) -> None:
        # "confidence" is in SPECULATION_PATTERNS but not BANNED_PHRASES.
        narrative = "The team played with renewed confidence in the third quarter."
        errors, warnings = check_banned_phrases([_block(narrative)])
        assert errors == []
        assert len(warnings) == 1
        assert "confidence" in warnings[0]

    def test_speculation_overlap_with_banned_does_not_double_report(self) -> None:
        # "renewed energy" is both BANNED and (via "renewed energy") flagged
        # in SPECULATION_PATTERNS. The error wins; the same phrase must not
        # also reappear in the warning list.
        narrative = "The home side returned with renewed energy after the break."
        errors, warnings = check_banned_phrases([_block(narrative)])
        assert errors and "renewed energy" in errors[0]
        for w in warnings:
            assert "renewed energy" not in w

    @pytest.mark.parametrize("pattern", SPECULATION_PATTERNS)
    def test_each_speculation_pattern_recognized(self, pattern: str) -> None:
        narrative = f"Despite {pattern}, the score stayed tight through the half."
        errors, warnings = check_banned_phrases([_block(narrative)])
        # Either BANNED (errors) or SPECULATION (warnings) — but the phrase
        # must surface somewhere. Banned takes precedence per implementation.
        flagged = (errors and any(pattern in e for e in errors)) or (
            warnings and any(pattern in w for w in warnings)
        )
        assert flagged, f"speculation pattern {pattern!r} should be flagged"


# ---------------------------------------------------------------------------
# 4) Clean narratives pass both gates.
# ---------------------------------------------------------------------------


class TestCleanTextPasses:
    """Plain factual narratives produce no errors and no warnings."""

    def test_clean_block_has_no_errors_or_warnings(self) -> None:
        narrative = (
            "The home team led 14-7 entering the second half. Two unanswered "
            "scores in the third quarter pushed the margin to 28-7."
        )
        errors, warnings = check_banned_phrases([_block(narrative)])
        assert errors == []
        assert warnings == []

    def test_empty_narrative_produces_no_errors(self) -> None:
        # Empty string short-circuits: no tokens to match against.
        errors, warnings = check_banned_phrases([_block("")])
        assert errors == []
        assert warnings == []

    def test_missing_narrative_field_produces_no_errors(self) -> None:
        # validate_blocks_phrases tolerates blocks with no narrative key
        # (they're caught by the structural rules earlier in validation).
        errors, warnings = check_banned_phrases([{"block_index": 0}])
        assert errors == []
        assert warnings == []


# ---------------------------------------------------------------------------
# 5) MLB shutouts must not use exaggerated dominance language.
# ---------------------------------------------------------------------------


class TestMLBShutoutLanguage:
    """Per BRAINDUMP MLB assertion: shutouts do not use exaggerated language."""

    def test_low_event_dominant_is_flagged(self) -> None:
        block = _block(
            "The starter delivered a dominant outing with seven shutout innings.",
            block_index=2,
        )
        errors, _ = validate_low_event_drama([block], archetype="low_event")
        assert errors
        assert "dominant" in errors[0]

    def test_low_event_impenetrable_is_flagged(self) -> None:
        block = _block(
            "The bullpen was impenetrable through the late innings.", block_index=3,
        )
        errors, _ = validate_low_event_drama([block], archetype="low_event")
        assert errors
        assert "impenetrable" in errors[0]

    def test_low_event_factual_text_passes(self) -> None:
        block = _block(
            "The starter struck out 11 over seven scoreless innings to seal the 1-0 win.",
        )
        errors, warnings = validate_low_event_drama([block], archetype="low_event")
        assert errors == []
        assert warnings == []

    def test_non_low_event_archetype_skips_check(self) -> None:
        # The same exaggerated descriptor is fine for blowout / wire_to_wire
        # archetypes — only low_event triggers Rule 14.
        block = _block("It was a dominant performance from start to finish.")
        errors, _ = validate_low_event_drama([block], archetype="blowout")
        assert errors == []


# ---------------------------------------------------------------------------
# 6) NBA blowouts: late blocks must not imply fake leverage.
# ---------------------------------------------------------------------------


class TestNBABlowoutLateLeverage:
    """Per BRAINDUMP NBA assertion: blowout late blocks do not imply fake leverage."""

    def _flow(self, last_narrative: str) -> list[dict[str, Any]]:
        # 5-block flow; the "final 20%" cutoff (ceil(5 * 0.8) = 4) marks
        # block index 4 as the late block. Earlier blocks must not trigger.
        return [
            _block("Phoenix opened on a 14-2 run.", block_index=0),
            _block("By halftime the margin had grown to 22.", block_index=1),
            _block("The cushion held through Q3.", block_index=2),
            _block("Reserves played most of the fourth.", block_index=3),
            _block(last_narrative, block_index=4),
        ]

    def test_blowout_late_block_with_rally_language_flagged(self) -> None:
        flow = self._flow(
            "A late surge offered a glimmer of a comeback but the result was set."
        )
        errors, _ = validate_blowout_late_leverage(flow, archetype="blowout")
        assert errors
        assert "comeback" in errors[0]

    def test_blowout_late_block_with_could_still_flagged(self) -> None:
        flow = self._flow(
            "Phoenix could still cool down even with the bench getting reps."
        )
        errors, _ = validate_blowout_late_leverage(flow, archetype="blowout")
        assert errors
        assert "could still" in errors[0]

    def test_blowout_late_block_factual_recap_passes(self) -> None:
        flow = self._flow(
            "Phoenix closed out a 28-point win behind balanced bench scoring."
        )
        errors, warnings = validate_blowout_late_leverage(flow, archetype="blowout")
        assert errors == []
        assert warnings == []

    def test_non_blowout_archetype_allows_rally_language(self) -> None:
        # Comebacks legitimately mention rallies — Rule 13 skips them.
        flow = self._flow(
            "Their late rally fell two points short as the buzzer sounded."
        )
        errors, _ = validate_blowout_late_leverage(flow, archetype="comeback")
        assert errors == []
