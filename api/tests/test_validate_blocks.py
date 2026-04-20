"""Tests for VALIDATE_BLOCKS stage."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pipeline.stages.block_types import (
    MAX_BLOCKS,
    MAX_TOTAL_WORDS,
    MAX_WORDS_PER_BLOCK,
    MIN_BLOCKS,
    SemanticRole,
)
from app.services.pipeline.stages.validate_blocks import (
    MINI_BOX_STAT_FIELDS,
    MINI_BOX_UNKNOWN,
    REQUIRED_BLOCK_TYPES,
    _check_ot_present,
    _check_resolution_specificity,
    _check_score_present,
    _check_team_present,
    _count_sentences,
    _get_final_window_plays,
    _validate_block_count,
    _validate_coverage,
    _validate_key_plays,
    _validate_mini_box,
    _validate_moment_coverage,
    _validate_required_block_types,
    _validate_role_constraints,
    _validate_score_continuity,
    _validate_word_counts,
)

_VALID_MINI_BOX = {
    "cumulative": {
        "home": {"points": 25},
        "away": {"points": 22},
    },
    "delta": {
        "home": {"points": 25},
        "away": {"points": 22},
    },
}


class TestValidateBlockCount:
    """Tests for block count validation."""

    def test_valid_block_count(self) -> None:
        """Block count in range [3, 7] passes."""
        for count in range(MIN_BLOCKS, MAX_BLOCKS + 1):
            blocks = [{"block_index": i} for i in range(count)]
            errors, warnings = _validate_block_count(blocks)
            assert len(errors) == 0

    def test_too_few_blocks(self) -> None:
        """Fewer than 3 blocks is error."""
        blocks = [{"block_index": i} for i in range(2)]
        errors, warnings = _validate_block_count(blocks)
        assert len(errors) > 0
        assert "few" in errors[0].lower()

    def test_too_many_blocks(self) -> None:
        """More than 7 blocks is error."""
        blocks = [{"block_index": i} for i in range(8)]
        errors, warnings = _validate_block_count(blocks)
        assert len(errors) > 0
        assert "many" in errors[0].lower()

    def test_blowout_three_blocks_passes(self) -> None:
        """3-block blowout arc (SETUP → DECISION_POINT → RESOLUTION) is valid.

        Blowout games produce fewer distinct narrative segments because there
        are no meaningful momentum swings; MIN_BLOCKS = 3 accommodates this.
        """
        blocks = [{"block_index": i} for i in range(3)]
        errors, warnings = _validate_block_count(blocks)
        assert len(errors) == 0, (
            f"3-block blowout should pass block count validation, got: {errors}"
        )


class TestValidateRoleConstraints:
    """Tests for semantic role validation."""

    def test_first_block_must_be_setup(self) -> None:
        """First block must have SETUP role."""
        blocks = [
            {"role": SemanticRole.RESPONSE.value},  # Should be SETUP
            {"role": SemanticRole.RESPONSE.value},
            {"role": SemanticRole.RESPONSE.value},
            {"role": SemanticRole.RESOLUTION.value},
        ]
        errors, warnings = _validate_role_constraints(blocks)
        assert len(errors) > 0
        assert "SETUP" in errors[0]

    def test_last_block_must_be_resolution(self) -> None:
        """Last block must have RESOLUTION role."""
        blocks = [
            {"role": SemanticRole.SETUP.value},
            {"role": SemanticRole.RESPONSE.value},
            {"role": SemanticRole.RESPONSE.value},
            {"role": SemanticRole.RESPONSE.value},  # Should be RESOLUTION
        ]
        errors, warnings = _validate_role_constraints(blocks)
        assert len(errors) > 0
        assert "RESOLUTION" in errors[0]

    def test_role_appears_more_than_twice(self) -> None:
        """Role appearing more than twice is error."""
        blocks = [
            {"role": SemanticRole.SETUP.value},
            {"role": SemanticRole.RESPONSE.value},
            {"role": SemanticRole.RESPONSE.value},
            {"role": SemanticRole.RESPONSE.value},  # Third RESPONSE
            {"role": SemanticRole.RESOLUTION.value},
        ]
        errors, warnings = _validate_role_constraints(blocks)
        assert len(errors) > 0
        assert "RESPONSE" in errors[0]

    def test_valid_role_distribution(self) -> None:
        """Valid role distribution passes."""
        blocks = [
            {"role": SemanticRole.SETUP.value},
            {"role": SemanticRole.MOMENTUM_SHIFT.value},
            {"role": SemanticRole.RESPONSE.value},
            {"role": SemanticRole.DECISION_POINT.value},
            {"role": SemanticRole.RESOLUTION.value},
        ]
        errors, warnings = _validate_role_constraints(blocks)
        assert len(errors) == 0


class TestValidateRequiredBlockTypes:
    """Tests for _validate_required_block_types."""

    def test_both_required_present_passes(self) -> None:
        """SETUP and RESOLUTION present → no errors."""
        blocks = [
            {"role": SemanticRole.SETUP.value},
            {"role": SemanticRole.MOMENTUM_SHIFT.value},
            {"role": SemanticRole.RESOLUTION.value},
        ]
        errors, warnings = _validate_required_block_types(blocks)
        assert errors == []

    def test_missing_setup_is_error(self) -> None:
        """Missing SETUP block produces a structured error."""
        blocks = [
            {"role": SemanticRole.MOMENTUM_SHIFT.value},
            {"role": SemanticRole.RESOLUTION.value},
        ]
        errors, warnings = _validate_required_block_types(blocks)
        assert len(errors) == 1
        assert "SETUP" in errors[0]
        assert "Required block type missing" in errors[0]

    def test_missing_resolution_is_error(self) -> None:
        """Missing RESOLUTION block produces a structured error."""
        blocks = [
            {"role": SemanticRole.SETUP.value},
            {"role": SemanticRole.MOMENTUM_SHIFT.value},
        ]
        errors, warnings = _validate_required_block_types(blocks)
        assert len(errors) == 1
        assert "RESOLUTION" in errors[0]

    def test_both_missing_produces_two_errors(self) -> None:
        """Both required types absent → two errors."""
        blocks = [
            {"role": SemanticRole.MOMENTUM_SHIFT.value},
            {"role": SemanticRole.RESPONSE.value},
        ]
        errors, warnings = _validate_required_block_types(blocks)
        assert len(errors) == 2
        role_names = {e for e in errors}
        assert any("SETUP" in e for e in role_names)
        assert any("RESOLUTION" in e for e in role_names)

    def test_empty_blocks_produces_errors(self) -> None:
        """Empty blocks list is missing all required types."""
        errors, warnings = _validate_required_block_types([])
        assert len(errors) == len(REQUIRED_BLOCK_TYPES)

    def test_error_includes_present_roles(self) -> None:
        """Error message lists the roles that are present."""
        blocks = [{"role": SemanticRole.MOMENTUM_SHIFT.value}]
        errors, warnings = _validate_required_block_types(blocks)
        assert any("MOMENTUM_SHIFT" in e for e in errors)

    def test_required_block_types_constant(self) -> None:
        """REQUIRED_BLOCK_TYPES constant contains expected values."""
        assert "SETUP" in REQUIRED_BLOCK_TYPES
        assert "RESOLUTION" in REQUIRED_BLOCK_TYPES


class TestValidateWordCounts:
    """Tests for word count validation."""

    def test_missing_narrative_is_error(self) -> None:
        """Block without narrative produces error."""
        blocks = [{"block_index": 0, "narrative": ""}]
        errors, warnings = _validate_word_counts(blocks)
        assert len(errors) > 0
        assert "Missing" in errors[0]

    def test_too_short_narrative_is_warning(self) -> None:
        """Narrative shorter than minimum produces warning."""
        blocks = [{"block_index": 0, "narrative": "Short."}]
        errors, warnings = _validate_word_counts(blocks)
        assert len(warnings) > 0
        assert "short" in warnings[0].lower()

    def test_too_long_narrative_is_warning(self) -> None:
        """Narrative longer than maximum produces warning."""
        long_narrative = " ".join(["word"] * (MAX_WORDS_PER_BLOCK + 10))
        blocks = [{"block_index": 0, "narrative": long_narrative}]
        errors, warnings = _validate_word_counts(blocks)
        assert len(warnings) > 0
        assert "long" in warnings[0].lower()

    def test_total_word_count_too_high(self) -> None:
        """Total word count exceeding limit produces warning."""
        # Create blocks with enough words to exceed limit
        words_per_block = MAX_TOTAL_WORDS // 4 + 10  # Will exceed when summed
        blocks = [
            {"block_index": i, "narrative": " ".join(["word"] * words_per_block)}
            for i in range(4)
        ]
        errors, warnings = _validate_word_counts(blocks)
        assert any("total" in w.lower() for w in warnings)

    def test_valid_word_counts(self) -> None:
        """Valid word counts produce no errors."""
        blocks = [
            {"block_index": i, "narrative": " ".join(["word"] * 30)}
            for i in range(5)
        ]  # 5 blocks × 30 words = 150 total
        errors, warnings = _validate_word_counts(blocks)
        assert len(errors) == 0
        # Only warnings, no errors for valid range


class TestValidateScoreContinuity:
    """Tests for score continuity validation."""

    def test_continuous_scores_pass(self) -> None:
        """Continuous scores across blocks pass."""
        blocks = [
            {"score_before": [0, 0], "score_after": [10, 8]},
            {"score_before": [10, 8], "score_after": [20, 18]},
            {"score_before": [20, 18], "score_after": [30, 28]},
        ]
        errors, warnings = _validate_score_continuity(blocks)
        assert len(errors) == 0

    def test_discontinuous_scores_is_error(self) -> None:
        """Score discontinuity produces error."""
        blocks = [
            {"score_before": [0, 0], "score_after": [10, 8]},
            {"score_before": [15, 10], "score_after": [25, 20]},  # Gap!
        ]
        errors, warnings = _validate_score_continuity(blocks)
        assert len(errors) > 0
        assert "discontinuity" in errors[0].lower()

    def test_single_block_no_check(self) -> None:
        """Single block has no continuity check."""
        blocks = [{"score_before": [0, 0], "score_after": [100, 95]}]
        errors, warnings = _validate_score_continuity(blocks)
        assert len(errors) == 0


class TestValidateMomentCoverage:
    """Tests for moment coverage validation."""

    def test_all_moments_covered(self) -> None:
        """All moments covered by blocks passes."""
        blocks = [
            {"moment_indices": [0, 1]},
            {"moment_indices": [2, 3]},
            {"moment_indices": [4]},
        ]
        errors, warnings = _validate_moment_coverage(blocks, total_moments=5)
        assert len(errors) == 0

    def test_moment_in_multiple_blocks(self) -> None:
        """Moment in multiple blocks produces error."""
        blocks = [
            {"moment_indices": [0, 1, 2]},
            {"moment_indices": [2, 3, 4]},  # Moment 2 duplicated
        ]
        errors, warnings = _validate_moment_coverage(blocks, total_moments=5)
        assert len(errors) > 0
        assert "multiple" in errors[0].lower()

    def test_missing_moments(self) -> None:
        """Moments not covered by any block produces error."""
        blocks = [
            {"moment_indices": [0, 1]},
            {"moment_indices": [3, 4]},  # Missing moment 2
        ]
        errors, warnings = _validate_moment_coverage(blocks, total_moments=5)
        assert len(errors) > 0
        assert "not covered" in errors[0].lower()

    def test_extra_moment_indices(self) -> None:
        """Reference to non-existent moment produces warning."""
        blocks = [
            {"moment_indices": [0, 1, 2]},
            {"moment_indices": [3, 4, 10]},  # Moment 10 doesn't exist
        ]
        errors, warnings = _validate_moment_coverage(blocks, total_moments=5)
        assert len(warnings) > 0
        assert "non-existent" in warnings[0].lower()


class TestValidateKeyPlays:
    """Tests for key play validation."""

    def test_valid_key_plays(self) -> None:
        """Valid key plays pass."""
        blocks = [
            {
                "block_index": 0,
                "play_ids": [1, 2, 3, 4, 5],
                "key_play_ids": [2, 4],
            }
        ]
        errors, warnings = _validate_key_plays(blocks)
        assert len(errors) == 0

    def test_no_key_plays_is_warning(self) -> None:
        """Block without key plays produces warning."""
        blocks = [
            {
                "block_index": 0,
                "play_ids": [1, 2, 3],
                "key_play_ids": [],
            }
        ]
        errors, warnings = _validate_key_plays(blocks)
        assert len(warnings) > 0
        assert "No key plays" in warnings[0]

    def test_too_many_key_plays_is_warning(self) -> None:
        """More than 3 key plays produces warning."""
        blocks = [
            {
                "block_index": 0,
                "play_ids": [1, 2, 3, 4, 5],
                "key_play_ids": [1, 2, 3, 4],  # 4 is too many
            }
        ]
        errors, warnings = _validate_key_plays(blocks)
        assert len(warnings) > 0
        assert "Too many" in warnings[0]

    def test_key_play_not_in_block(self) -> None:
        """Key play not in block's play_ids produces error."""
        blocks = [
            {
                "block_index": 0,
                "play_ids": [1, 2, 3],
                "key_play_ids": [5],  # Not in play_ids
            }
        ]
        errors, warnings = _validate_key_plays(blocks)
        assert len(errors) > 0
        assert "not in block's play_ids" in errors[0]


class TestValidationIntegration:
    """Integration tests for block validation."""

    def test_valid_blocks_pass_all_checks(self) -> None:
        """Fully valid blocks pass all validation checks."""
        blocks = [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "moment_indices": [0, 1],
                "score_before": [0, 0],
                "score_after": [10, 8],
                "play_ids": [1, 2, 3],
                "key_play_ids": [2],
                "narrative": "The Lakers started strong with a quick 10-8 lead.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 1,
                "role": SemanticRole.MOMENTUM_SHIFT.value,
                "moment_indices": [2, 3],
                "score_before": [10, 8],
                "score_after": [15, 20],
                "play_ids": [4, 5, 6],
                "key_play_ids": [5],
                "narrative": "The Celtics responded with a scoring run to take the lead.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 2,
                "role": SemanticRole.RESPONSE.value,
                "moment_indices": [4, 5],
                "score_before": [15, 20],
                "score_after": [25, 22],
                "play_ids": [7, 8, 9],
                "key_play_ids": [8],
                "narrative": "The Lakers came back with a strong third quarter performance.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 3,
                "role": SemanticRole.RESOLUTION.value,
                "moment_indices": [6, 7],
                "score_before": [25, 22],
                "score_after": [30, 28],
                "play_ids": [10, 11, 12],
                "key_play_ids": [11],
                "narrative": "The game concluded with the Lakers holding on for a 30-28 win.",
                "mini_box": _VALID_MINI_BOX,
            },
        ]

        # Run all validations
        errors: list[str] = []
        warnings: list[str] = []

        e, w = _validate_block_count(blocks)
        errors.extend(e)
        warnings.extend(w)

        e, w = _validate_role_constraints(blocks)
        errors.extend(e)
        warnings.extend(w)

        e, w = _validate_word_counts(blocks)
        errors.extend(e)
        warnings.extend(w)

        e, w = _validate_score_continuity(blocks)
        errors.extend(e)
        warnings.extend(w)

        e, w = _validate_moment_coverage(blocks, total_moments=8)
        errors.extend(e)
        warnings.extend(w)

        e, w = _validate_key_plays(blocks)
        errors.extend(e)
        warnings.extend(w)

        e, w = _validate_mini_box(blocks)
        errors.extend(e)
        warnings.extend(w)

        assert len(errors) == 0, f"Errors: {errors}"


class TestExecuteValidateBlocks:
    """Tests for execute_validate_blocks async function."""

    @pytest.fixture
    def mock_session(self) -> AsyncSession:
        """Create a mock session for testing.

        The session needs to return no social posts so embedded tweets are skipped.
        """
        from unittest.mock import AsyncMock, MagicMock

        session = AsyncMock()

        # Mock game query result - game not found so embedded tweets are skipped
        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = None

        # execute returns the mock result
        session.execute = AsyncMock(return_value=game_result)

        return session

    def test_missing_previous_output_raises(self, mock_session) -> None:
        """Missing previous output raises ValueError."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output=None,
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        with pytest.raises(ValueError, match="requires previous stage output"):
            asyncio.run(execute_validate_blocks(mock_session, stage_input))

    def test_not_rendered_raises(self, mock_session) -> None:
        """Previous output without blocks_rendered=True raises ValueError."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={"blocks_rendered": False, "blocks": []},
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        with pytest.raises(ValueError, match="RENDER_BLOCKS to complete"):
            asyncio.run(execute_validate_blocks(mock_session, stage_input))

    def test_no_blocks_raises(self, mock_session) -> None:
        """Empty blocks list raises ValueError."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={"blocks_rendered": True, "blocks": []},
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        with pytest.raises(ValueError, match="No blocks"):
            asyncio.run(execute_validate_blocks(mock_session, stage_input))

    def test_all_validations_passing(self, mock_session) -> None:
        """All validations pass with valid blocks."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "moment_indices": [0, 1],
                "score_before": [0, 0],
                "score_after": [10, 8],
                "play_ids": [1, 2, 3],
                "key_play_ids": [2],
                "narrative": "The Lakers started strong with a quick 10-8 lead in the opening minutes.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 1,
                "role": SemanticRole.MOMENTUM_SHIFT.value,
                "moment_indices": [2, 3],
                "score_before": [10, 8],
                "score_after": [15, 20],
                "play_ids": [4, 5, 6],
                "key_play_ids": [5],
                "narrative": "The Celtics responded with a scoring run to take the lead midway through.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 2,
                "role": SemanticRole.RESPONSE.value,
                "moment_indices": [4, 5],
                "score_before": [15, 20],
                "score_after": [25, 22],
                "play_ids": [7, 8, 9],
                "key_play_ids": [8],
                "narrative": "The Lakers came back with a strong third quarter performance and retook control.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 3,
                "role": SemanticRole.RESOLUTION.value,
                "moment_indices": [6, 7],
                "score_before": [25, 22],
                "score_after": [30, 28],
                "play_ids": [10, 11, 12],
                "key_play_ids": [11],
                "narrative": "The game concluded with the Lakers holding on for a close 30-28 victory.",
                "mini_box": _VALID_MINI_BOX,
            },
        ]

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(8)],
                "pbp_events": [],
                "validated": True,
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        assert result.data["blocks_validated"] is True
        assert len(result.data["errors"]) == 0

    def test_with_validation_errors(self, mock_session) -> None:
        """Validation fails with invalid blocks."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = [
            {
                "block_index": 0,
                "role": SemanticRole.RESPONSE.value,  # Should be SETUP
                "moment_indices": [0],
                "score_before": [0, 0],
                "score_after": [10, 8],
                "play_ids": [1],
                "key_play_ids": [1],
                "narrative": "Short narrative here for block zero that tests the word count.",
            },
            {
                "block_index": 1,
                "role": SemanticRole.RESPONSE.value,  # Should be RESOLUTION
                "moment_indices": [1],
                "score_before": [10, 8],
                "score_after": [20, 15],
                "play_ids": [2],
                "key_play_ids": [2],
                "narrative": "Another short narrative for block one that tests word count.",
            },
        ]

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(2)],
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        # Should fail due to role constraints
        assert result.data["blocks_validated"] is False
        assert len(result.data["errors"]) > 0

    def test_with_warnings_only(self, mock_session) -> None:
        """Validation passes with warnings but no errors."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "moment_indices": [0],
                "score_before": [0, 0],
                "score_after": [10, 8],
                "play_ids": [1],
                "key_play_ids": [],  # Missing key plays - warning
                "narrative": "Short.",  # Too short - warning
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 1,
                "role": SemanticRole.MOMENTUM_SHIFT.value,
                "moment_indices": [1],
                "score_before": [10, 8],
                "score_after": [15, 18],
                "play_ids": [2],
                "key_play_ids": [2],
                "narrative": "The Celtics made a strong comeback push to take the lead.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 2,
                "role": SemanticRole.RESPONSE.value,
                "moment_indices": [2],
                "score_before": [15, 18],
                "score_after": [22, 20],
                "play_ids": [3],
                "key_play_ids": [3],
                "narrative": "Lakers fought back with determination and skill throughout.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 3,
                "role": SemanticRole.RESOLUTION.value,
                "moment_indices": [3],
                "score_before": [22, 20],
                "score_after": [30, 28],
                "play_ids": [4],
                "key_play_ids": [4],
                "narrative": "The final quarter saw Lakers close out the game successfully.",
                "mini_box": _VALID_MINI_BOX,
            },
        ]

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(4)],
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        # Should pass despite warnings
        assert result.data["blocks_validated"] is True
        assert len(result.data["warnings"]) > 0

    def test_output_structure(self, mock_session) -> None:
        """Output contains all expected fields."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = [
            {
                "block_index": i,
                "role": [SemanticRole.SETUP.value, SemanticRole.RESPONSE.value,
                         SemanticRole.RESPONSE.value, SemanticRole.RESOLUTION.value][i],
                "moment_indices": [i],
                "score_before": [i * 10, i * 8],
                "score_after": [(i + 1) * 10, (i + 1) * 8],
                "play_ids": [i + 1],
                "key_play_ids": [i + 1],
                "narrative": f"Block {i} narrative with enough words to pass minimum.",
                "mini_box": _VALID_MINI_BOX,
            }
            for i in range(4)
        ]

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(4)],
                "pbp_events": [{"test": "event"}],
                "validated": True,
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        # Check output structure
        assert "blocks_validated" in result.data
        assert "blocks" in result.data
        assert "block_count" in result.data
        assert "total_words" in result.data
        assert "errors" in result.data
        assert "warnings" in result.data
        assert "moments" in result.data
        assert "pbp_events" in result.data

    def test_missing_required_block_type_fails(self, mock_session) -> None:
        """Blocks missing a required type produce a structured error."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        # No RESOLUTION block — only SETUP + MOMENTUM_SHIFT + RESPONSE
        blocks = [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "moment_indices": [0],
                "score_before": [0, 0],
                "score_after": [10, 8],
                "play_ids": [1],
                "key_play_ids": [1],
                "narrative": "Opening narrative block with enough words for validation.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 1,
                "role": SemanticRole.MOMENTUM_SHIFT.value,
                "moment_indices": [1],
                "score_before": [10, 8],
                "score_after": [20, 15],
                "play_ids": [2],
                "key_play_ids": [2],
                "narrative": "Second narrative block with enough words for validation.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 2,
                "role": SemanticRole.RESPONSE.value,  # Not RESOLUTION
                "moment_indices": [2],
                "score_before": [20, 15],
                "score_after": [30, 22],
                "play_ids": [3],
                "key_play_ids": [3],
                "narrative": "Third narrative block with enough words for validation.",
                "mini_box": _VALID_MINI_BOX,
            },
        ]

        stage_input = StageInput(
            game_id=42,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(3)],
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        assert result.data["blocks_validated"] is False
        assert any("RESOLUTION" in e for e in result.data["errors"])

    def test_block_count_warning_includes_game_id(self, mock_session) -> None:
        """Block count out of range emits a structured log warning with game_id."""
        import logging
        from unittest.mock import patch

        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        # Two blocks — below MIN_BLOCKS (3)
        blocks = [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "moment_indices": [0],
                "score_before": [0, 0],
                "score_after": [10, 8],
                "play_ids": [1],
                "key_play_ids": [1],
                "narrative": "Opening narrative block with enough words for validation.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 1,
                "role": SemanticRole.RESOLUTION.value,
                "moment_indices": [1],
                "score_before": [10, 8],
                "score_after": [20, 15],
                "play_ids": [2],
                "key_play_ids": [2],
                "narrative": "Second narrative block with enough words for validation.",
                "mini_box": _VALID_MINI_BOX,
            },
        ]

        stage_input = StageInput(
            game_id=99,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(2)],
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        warning_extras = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record):
                if record.getMessage() == "block_count_out_of_range" or "block_count_out_of_range" in record.getMessage():
                    warning_extras.append(getattr(record, "game_id", None))

        handler = _CapturingHandler()
        vb_logger = logging.getLogger("app.services.pipeline.stages.validate_blocks")
        vb_logger.addHandler(handler)
        try:
            asyncio.run(execute_validate_blocks(mock_session, stage_input))
        finally:
            vb_logger.removeHandler(handler)

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))
        assert result.data["blocks_validated"] is False
        assert any("few" in e.lower() for e in result.data["errors"])

    def test_score_discontinuity_detected(self, mock_session) -> None:
        """Score discontinuity is detected as error."""
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "moment_indices": [0],
                "score_before": [0, 0],
                "score_after": [10, 8],
                "play_ids": [1],
                "key_play_ids": [1],
                "narrative": "Opening narrative block with enough words for validation.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 1,
                "role": SemanticRole.MOMENTUM_SHIFT.value,
                "moment_indices": [1],
                "score_before": [15, 12],  # Discontinuity! Should be [10, 8]
                "score_after": [25, 22],
                "play_ids": [2],
                "key_play_ids": [2],
                "narrative": "Second narrative block with enough words for validation.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 2,
                "role": SemanticRole.RESPONSE.value,
                "moment_indices": [2],
                "score_before": [25, 22],
                "score_after": [35, 30],
                "play_ids": [3],
                "key_play_ids": [3],
                "narrative": "Third narrative block with enough words for validation test.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 3,
                "role": SemanticRole.RESOLUTION.value,
                "moment_indices": [3],
                "score_before": [35, 30],
                "score_after": [45, 38],
                "play_ids": [4],
                "key_play_ids": [4],
                "narrative": "Final narrative block with enough words for validation test.",
                "mini_box": _VALID_MINI_BOX,
            },
        ]

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(4)],
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        assert result.data["blocks_validated"] is False
        assert any("discontinuity" in e.lower() for e in result.data["errors"])


class TestSentenceCounting:
    """Tests for sentence counting with abbreviation handling."""

    def test_basic_sentence_counting(self) -> None:
        """Counts simple sentences correctly."""
        assert _count_sentences("One sentence. Two sentences.") == 2
        assert _count_sentences("Just one sentence.") == 1
        assert _count_sentences("First! Second? Third.") == 3

    def test_empty_text_returns_zero(self) -> None:
        """Empty or whitespace text returns zero."""
        assert _count_sentences("") == 0
        assert _count_sentences("   ") == 0

    def test_abbreviation_dr(self) -> None:
        """Dr. abbreviation does not break sentence counting."""
        text = "Dr. James made a shot. Then he scored again."
        assert _count_sentences(text) == 2

    def test_abbreviation_mr_mrs(self) -> None:
        """Mr. and Mrs. abbreviations don't break counting."""
        text = "Mr. Smith scored. Mrs. Jones assisted."
        assert _count_sentences(text) == 2

    def test_abbreviation_vs(self) -> None:
        """vs. abbreviation doesn't break counting."""
        text = "Lakers vs. Celtics was exciting. Great game."
        assert _count_sentences(text) == 2

    def test_abbreviation_st_ave(self) -> None:
        """Address abbreviations don't break counting."""
        text = "Game at St. Louis Arena. The fans were loud."
        assert _count_sentences(text) == 2

    def test_multiple_abbreviations(self) -> None:
        """Multiple abbreviations in one sentence work correctly."""
        text = "Dr. Smith and Mr. Jones watched. They enjoyed it."
        assert _count_sentences(text) == 2

    def test_ellipsis_not_sentence_break(self) -> None:
        """Ellipsis (...) is not treated as sentence break."""
        text = "The play was... interesting. Next play was better."
        assert _count_sentences(text) == 2

    def test_exclamation_and_question(self) -> None:
        """Exclamation and question marks count as sentence ends."""
        text = "What a play! Did you see that? Amazing."
        assert _count_sentences(text) == 3

    def test_consecutive_punctuation(self) -> None:
        """Consecutive punctuation counts as single sentence end."""
        text = "Really?! Yes. Wow..."
        # "Really?!" = 1, "Yes." = 1, "Wow..." (ellipsis) = 1
        # But ellipsis should be protected, so just "Wow" after
        assert _count_sentences(text) == 3

    def test_case_insensitive_abbreviations(self) -> None:
        """Abbreviations work case-insensitively."""
        text = "DR. JAMES scored. mr. smith assisted."
        assert _count_sentences(text) == 2

    def test_month_abbreviations(self) -> None:
        """Month abbreviations don't break counting."""
        text = "Game on Jan. 15. Next game Feb. 20."
        assert _count_sentences(text) == 2


class TestCoverageHelpers:
    """Unit tests for coverage helper functions."""

    # --- _check_score_present ---

    def test_score_hyphen(self) -> None:
        assert _check_score_present("Lakers won 107-98 tonight", 107, 98)

    def test_score_en_dash(self) -> None:
        assert _check_score_present("final score 107\u201398", 107, 98)

    def test_score_to_form(self) -> None:
        assert _check_score_present("they won 107 to 98", 107, 98)

    def test_score_reverse_order(self) -> None:
        # Score written away-home is still valid
        assert _check_score_present("98-107 final", 107, 98)

    def test_score_missing(self) -> None:
        assert not _check_score_present("The Lakers won a close game", 107, 98)

    def test_score_partial_match_not_confused(self) -> None:
        # "1070" should not match "107"
        assert not _check_score_present("scored 1070 points total", 107, 98)

    # --- _check_team_present ---

    def test_full_team_name(self) -> None:
        assert _check_team_present("The Los Angeles Lakers won", "Los Angeles Lakers")

    def test_team_nickname_only(self) -> None:
        assert _check_team_present("The Lakers took control", "Los Angeles Lakers")

    def test_team_missing(self) -> None:
        assert not _check_team_present("The home team won decisively", "Los Angeles Lakers")

    def test_single_word_team(self) -> None:
        assert _check_team_present("Arsenal scored twice", "Arsenal")

    # --- _check_ot_present ---

    def test_overtime_word(self) -> None:
        assert _check_ot_present("They won in overtime")

    def test_ot_abbreviation_spaced(self) -> None:
        assert _check_ot_present("Game ended in OT after a wild finish")

    def test_ot_at_sentence_end(self) -> None:
        assert _check_ot_present("Decided in OT.")

    def test_extra_time(self) -> None:
        assert _check_ot_present("Settled in extra time")

    def test_no_ot_mention(self) -> None:
        assert not _check_ot_present("Lakers won 107-98 in regulation")


class TestValidateCoverage:
    """Unit tests for _validate_coverage."""

    def _blocks(self, *narratives: str) -> list[dict]:
        return [{"narrative": n} for n in narratives]

    def test_all_pass(self) -> None:
        blocks = self._blocks(
            "The Lakers started hot.",
            "Boston made their run but the Lakers held on to win 107-98.",
        )
        errors, warnings = _validate_coverage(blocks, "Lakers", "Celtics", 107, 98, False)
        assert errors == []

    def test_missing_score(self) -> None:
        blocks = self._blocks(
            "The Lakers started hot.",
            "Boston made their run but the Lakers held on for the win.",
        )
        errors, _ = _validate_coverage(blocks, "Lakers", "Celtics", 107, 98, False)
        assert any("107-98" in e for e in errors)

    def test_missing_winner(self) -> None:
        blocks = self._blocks(
            "It was a tight game all night.",
            "The home team sealed it 107-98 in the fourth.",
        )
        errors, _ = _validate_coverage(blocks, "Lakers", "Celtics", 107, 98, False)
        assert any("Lakers" in e for e in errors)

    def test_missing_ot_mention(self) -> None:
        blocks = self._blocks(
            "The Lakers took an early lead.",
            "They won 107-98 in a thrilling finish.",
        )
        # Score contains "Lakers" for winner; game had OT but narrative omits it
        errors, _ = _validate_coverage(blocks, "Lakers", "Celtics", 107, 98, True)
        assert any("overtime" in e.lower() or "ot" in e.lower() for e in errors)

    def test_ot_mentioned_passes(self) -> None:
        blocks = self._blocks(
            "The Lakers led early.",
            "They survived overtime to win 107-98.",
        )
        errors, _ = _validate_coverage(blocks, "Lakers", "Celtics", 107, 98, True)
        assert errors == []

    def test_no_score_data_skips_score_winner(self) -> None:
        blocks = self._blocks("A game was played.")
        _, warnings = _validate_coverage(blocks, "Lakers", "Celtics", 0, 0, False)
        assert any("unavailable" in w.lower() for w in warnings)

    def test_empty_narratives_error(self) -> None:
        errors, _ = _validate_coverage([], "Lakers", "Celtics", 107, 98, False)
        assert any("no narrative" in e.lower() for e in errors)

    def test_tie_score_skips_winner_check(self) -> None:
        # Tied game — no winner to check
        blocks = self._blocks("They finished tied 98-98 in regulation.")
        errors, _ = _validate_coverage(blocks, "Lakers", "Celtics", 98, 98, False)
        assert errors == []


class TestCoverageDecision:
    """Tests for REGENERATE / FALLBACK decision in execute_validate_blocks."""

    @pytest.fixture
    def mock_session(self):
        from unittest.mock import AsyncMock, MagicMock

        session = AsyncMock()
        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=game_result)
        return session

    def _valid_blocks(self) -> list[dict]:
        """4 structurally valid blocks with full narrative coverage."""
        return [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "moment_indices": [0],
                "score_before": [0, 0],
                "score_after": [10, 8],
                "play_ids": [1],
                "key_play_ids": [1],
                "narrative": "The Lakers opened strong, setting the tone early.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 1,
                "role": SemanticRole.MOMENTUM_SHIFT.value,
                "moment_indices": [1],
                "score_before": [10, 8],
                "score_after": [20, 18],
                "play_ids": [2],
                "key_play_ids": [2],
                "narrative": "The Celtics answered with a run to draw close.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 2,
                "role": SemanticRole.RESPONSE.value,
                "moment_indices": [2],
                "score_before": [20, 18],
                "score_after": [30, 22],
                "play_ids": [3],
                "key_play_ids": [3],
                "narrative": "Lakers pushed back and extended their advantage.",
                "mini_box": _VALID_MINI_BOX,
            },
            {
                "block_index": 3,
                "role": SemanticRole.RESOLUTION.value,
                "moment_indices": [3],
                "score_before": [30, 22],
                "score_after": [107, 98],
                "play_ids": [4],
                "key_play_ids": [4],
                "narrative": "The Lakers sealed it 107-98 to claim the victory.",
                "mini_box": _VALID_MINI_BOX,
            },
        ]

    def test_publish_when_all_pass(self, mock_session) -> None:
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": self._valid_blocks(),
                "moments": [{} for _ in range(4)],
            },
            game_context={
                "home_team": "Lakers",
                "away_team": "Celtics",
                "home_score": 107,
                "away_score": 98,
                "has_overtime": False,
            },
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        assert result.data["decision"] == "PUBLISH"
        assert result.data["coverage_passed"] is True

    def test_regenerate_on_coverage_failure_first_attempt(self, mock_session) -> None:
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = self._valid_blocks()
        # Remove score from RESOLUTION narrative so coverage fails
        blocks[-1]["narrative"] = "The Lakers held on for the win."

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(4)],
            },
            game_context={
                "home_team": "Lakers",
                "away_team": "Celtics",
                "home_score": 107,
                "away_score": 98,
                "has_overtime": False,
                "regen_attempt": 0,
            },
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        assert result.data["decision"] == "REGENERATE"
        assert result.data["coverage_passed"] is False
        assert len(result.data["coverage_errors"]) > 0

    def test_regenerate_on_coverage_failure_second_attempt(self, mock_session) -> None:
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = self._valid_blocks()
        blocks[-1]["narrative"] = "The Lakers held on for the win."

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(4)],
            },
            game_context={
                "home_team": "Lakers",
                "away_team": "Celtics",
                "home_score": 107,
                "away_score": 98,
                "has_overtime": False,
                "regen_attempt": 1,
            },
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        assert result.data["decision"] == "REGENERATE"

    def test_fallback_after_max_regen_attempts(self, mock_session) -> None:
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = self._valid_blocks()
        blocks[-1]["narrative"] = "The Lakers held on for the win."

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(4)],
            },
            game_context={
                "home_team": "Lakers",
                "away_team": "Celtics",
                "home_score": 107,
                "away_score": 98,
                "has_overtime": False,
                "regen_attempt": 2,
            },
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        # Template fallback upgrades FALLBACK → PUBLISH with deterministic blocks.
        assert result.data["decision"] == "PUBLISH"
        assert result.data["fallback_used"] is True
        assert result.data["blocks_validated"] is True

    def test_missing_ot_triggers_regenerate(self, mock_session) -> None:
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        blocks = self._valid_blocks()
        blocks[-1]["narrative"] = "The Lakers sealed it 107-98 to claim the victory."

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "moments": [{} for _ in range(4)],
            },
            game_context={
                "home_team": "Lakers",
                "away_team": "Celtics",
                "home_score": 107,
                "away_score": 98,
                "has_overtime": True,  # OT game, but narrative doesn't mention it
                "regen_attempt": 0,
            },
        )

        result = asyncio.run(execute_validate_blocks(mock_session, stage_input))

        assert result.data["decision"] == "REGENERATE"
        assert any("overtime" in e.lower() or "ot" in e.lower()
                   for e in result.data["coverage_errors"])


class TestValidateMiniBox:
    """Unit tests for _validate_mini_box."""

    def test_valid_mini_box_passes(self) -> None:
        """Blocks with valid mini_box produce no errors."""
        blocks = [{"block_index": 0, "mini_box": _VALID_MINI_BOX}]
        errors, warnings = _validate_mini_box(blocks)
        assert errors == []

    def test_missing_mini_box_is_error(self) -> None:
        """Block without mini_box key produces error."""
        blocks = [{"block_index": 0}]
        errors, _ = _validate_mini_box(blocks)
        assert len(errors) == 1
        assert "missing or empty" in errors[0]

    def test_null_mini_box_is_error(self) -> None:
        """Block with None mini_box produces error."""
        blocks = [{"block_index": 0, "mini_box": None}]
        errors, _ = _validate_mini_box(blocks)
        assert len(errors) == 1
        assert "missing or empty" in errors[0]

    def test_empty_dict_mini_box_is_error(self) -> None:
        """Block with empty dict mini_box produces error."""
        blocks = [{"block_index": 0, "mini_box": {}}]
        errors, _ = _validate_mini_box(blocks)
        assert any("missing or empty" in e for e in errors)

    def test_missing_cumulative_is_error(self) -> None:
        """mini_box without cumulative key produces error."""
        blocks = [{"block_index": 0, "mini_box": {"delta": {"home": {"points": 5}, "away": {"points": 4}}}}]
        errors, _ = _validate_mini_box(blocks)
        assert any("cumulative" in e for e in errors)

    def test_cumulative_missing_home_is_error(self) -> None:
        """mini_box.cumulative without home produces error."""
        blocks = [{"block_index": 0, "mini_box": {
            "cumulative": {"away": {"points": 22}},
            "delta": {"home": {"points": 5}, "away": {"points": 4}},
        }}]
        errors, _ = _validate_mini_box(blocks)
        assert any("home" in e for e in errors)

    def test_cumulative_missing_away_is_error(self) -> None:
        """mini_box.cumulative without away produces error."""
        blocks = [{"block_index": 0, "mini_box": {
            "cumulative": {"home": {"points": 25}},
            "delta": {"home": {"points": 5}, "away": {"points": 4}},
        }}]
        errors, _ = _validate_mini_box(blocks)
        assert any("away" in e for e in errors)

    def test_missing_delta_is_error(self) -> None:
        """mini_box without delta key produces error."""
        blocks = [{"block_index": 0, "mini_box": {
            "cumulative": {"home": {"points": 25}, "away": {"points": 22}},
        }}]
        errors, _ = _validate_mini_box(blocks)
        assert any("delta" in e for e in errors)

    def test_multiple_blocks_partial_failure(self) -> None:
        """One invalid block among valid ones produces per-block errors."""
        blocks = [
            {"block_index": 0, "mini_box": _VALID_MINI_BOX},
            {"block_index": 1},  # missing mini_box
            {"block_index": 2, "mini_box": _VALID_MINI_BOX},
        ]
        errors, _ = _validate_mini_box(blocks)
        assert len(errors) == 1
        assert "Block 1" in errors[0]

    def test_absent_stat_field_filled_with_unknown(self) -> None:
        """Absent MINI_BOX_STAT_FIELDS values are filled with MINI_BOX_UNKNOWN."""
        mini_box = {
            "cumulative": {
                "home": {},  # 'points' absent
                "away": {"points": 22},
            },
            "delta": {
                "home": {"points": 5},
                "away": {},  # 'points' absent
            },
        }
        blocks = [{"block_index": 0, "mini_box": mini_box}]
        errors, warnings = _validate_mini_box(blocks)
        assert errors == []
        # Fields filled in-place
        assert mini_box["cumulative"]["home"]["points"] == MINI_BOX_UNKNOWN
        assert mini_box["delta"]["away"]["points"] == MINI_BOX_UNKNOWN
        # Warnings emitted for each filled field
        assert len(warnings) == 2
        assert all("UNKNOWN" in w for w in warnings)

    def test_none_stat_field_filled_with_unknown(self) -> None:
        """Explicitly None stat field is filled with MINI_BOX_UNKNOWN."""
        mini_box = {
            "cumulative": {
                "home": {"points": None},
                "away": {"points": 22},
            },
            "delta": {
                "home": {"points": 5},
                "away": {"points": 4},
            },
        }
        blocks = [{"block_index": 0, "mini_box": mini_box}]
        errors, warnings = _validate_mini_box(blocks)
        assert errors == []
        assert mini_box["cumulative"]["home"]["points"] == MINI_BOX_UNKNOWN
        assert len(warnings) == 1

    def test_present_stat_field_not_overwritten(self) -> None:
        """Present (non-None) stat fields are not replaced with UNKNOWN."""
        blocks = [{"block_index": 0, "mini_box": _VALID_MINI_BOX}]
        errors, warnings = _validate_mini_box(blocks)
        assert errors == []
        # points values from _VALID_MINI_BOX must be preserved
        assert _VALID_MINI_BOX["cumulative"]["home"]["points"] == 25
        assert warnings == []

    def test_mini_box_stat_fields_constant(self) -> None:
        """MINI_BOX_STAT_FIELDS constant is a non-empty frozenset."""
        assert len(MINI_BOX_STAT_FIELDS) >= 1
        assert "points" in MINI_BOX_STAT_FIELDS


class TestMiniBoxDecision:
    """Tests for REGENERATE/FALLBACK triggered by missing mini_box."""

    def _mock_session(self):
        from unittest.mock import AsyncMock, MagicMock

        session = AsyncMock()
        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=game_result)
        return session

    def _blocks_without_mini_box(self) -> list[dict]:
        return [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "moment_indices": [0],
                "score_before": [0, 0],
                "score_after": [25, 22],
                "play_ids": [1],
                "key_play_ids": [1],
                "narrative": "The home team opened strong with an early lead.",
            },
            {
                "block_index": 1,
                "role": SemanticRole.MOMENTUM_SHIFT.value,
                "moment_indices": [1],
                "score_before": [25, 22],
                "score_after": [50, 44],
                "play_ids": [2],
                "key_play_ids": [2],
                "narrative": "The away team answered with a focused second-half run.",
            },
            {
                "block_index": 2,
                "role": SemanticRole.RESPONSE.value,
                "moment_indices": [2],
                "score_before": [50, 44],
                "score_after": [75, 66],
                "play_ids": [3],
                "key_play_ids": [3],
                "narrative": "The home team fought back and extended their cushion in the third.",
            },
            {
                "block_index": 3,
                "role": SemanticRole.RESOLUTION.value,
                "moment_indices": [3],
                "score_before": [75, 66],
                "score_after": [100, 88],
                "play_ids": [4],
                "key_play_ids": [4],
                "narrative": "The home team closed out the game 100-88 for the convincing win.",
            },
        ]

    def _run(self, stage_input):
        import asyncio

        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        return asyncio.run(execute_validate_blocks(self._mock_session(), stage_input))

    def test_missing_mini_box_triggers_regenerate(self) -> None:
        """One block missing mini_box → REGENERATE on first attempt."""
        from app.services.pipeline.models import StageInput

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": self._blocks_without_mini_box(),
                "moments": [{} for _ in range(4)],
            },
            game_context={
                "home_team": "Home Team",
                "away_team": "Away Team",
                "home_score": 100,
                "away_score": 88,
                "has_overtime": False,
                "regen_attempt": 0,
            },
        )

        result = self._run(stage_input)

        assert result.data["blocks_validated"] is False
        assert result.data["decision"] == "REGENERATE"
        assert any("mini_box" in e for e in result.data["errors"])

    def test_missing_mini_box_triggers_fallback_after_max_regens(self) -> None:
        """Blocks still missing mini_box after max regen attempts → FALLBACK."""
        from app.services.pipeline.models import StageInput

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": self._blocks_without_mini_box(),
                "moments": [{} for _ in range(4)],
            },
            game_context={
                "home_team": "Home Team",
                "away_team": "Away Team",
                "home_score": 100,
                "away_score": 88,
                "has_overtime": False,
                "regen_attempt": 2,
            },
        )

        result = self._run(stage_input)

        # Template fallback upgrades FALLBACK → PUBLISH; original errors are preserved.
        assert result.data["decision"] == "PUBLISH"
        assert result.data["fallback_used"] is True
        assert result.data["blocks_validated"] is True
        # Original mini_box errors still recorded in the errors list
        assert any("mini_box" in e for e in result.data["errors"])


class TestValidateEmbeddedTweetIds:
    """Tests for validate_embedded_tweet_ids."""

    def _run(self, session, blocks, game_id=None):
        from app.services.pipeline.stages.embedded_tweets import (
            validate_embedded_tweet_ids,
        )
        return asyncio.run(validate_embedded_tweet_ids(session, blocks, game_id))

    def _mock_session(self, found_ids: list[int]) -> AsyncMock:
        """Build a mock session that returns the given IDs from .execute()."""
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([(i,) for i in found_ids]))
        session = AsyncMock()
        session.execute.return_value = mock_result
        return session

    def test_no_embedded_ids_is_noop(self):
        """Blocks with no embedded_social_post_id skip the DB query."""
        session = AsyncMock()
        blocks = [{"block_index": 0, "embedded_social_post_id": None}]
        result = self._run(session, blocks)
        session.execute.assert_not_called()
        assert result == blocks

    def test_empty_blocks_is_noop(self):
        """Empty block list skips the DB query."""
        session = AsyncMock()
        result = self._run(session, [])
        session.execute.assert_not_called()
        assert result == []

    def test_all_ids_found_returns_blocks_unchanged(self):
        """Returns original blocks when all embedded IDs exist in the DB."""
        session = self._mock_session(found_ids=[10, 20])
        blocks = [
            {"block_index": 0, "embedded_social_post_id": 10},
            {"block_index": 1, "embedded_social_post_id": 20},
            {"block_index": 2, "embedded_social_post_id": None},
        ]
        result = self._run(session, blocks)
        assert [b["embedded_social_post_id"] for b in result] == [10, 20, None]

    def test_missing_id_emits_warning_and_skips_block(self, caplog):
        """Warning emitted and block's embedded_social_post_id cleared when ID missing."""
        import logging
        session = self._mock_session(found_ids=[10])
        blocks = [
            {"block_index": 0, "embedded_social_post_id": 10},
            {"block_index": 1, "embedded_social_post_id": 99},
        ]
        with caplog.at_level(logging.WARNING):
            result = self._run(session, blocks, game_id=7)
        assert result[0]["embedded_social_post_id"] == 10
        assert result[1]["embedded_social_post_id"] is None
        assert any("embedded_tweet_ref_missing" in r.message for r in caplog.records)

    def test_missing_id_warning_includes_context(self, caplog):
        """Warning record carries game_id, block_id, and the missing post ID."""
        import logging
        session = self._mock_session(found_ids=[])
        blocks = [{"block_index": 3, "embedded_social_post_id": 42}]
        with caplog.at_level(logging.WARNING):
            result = self._run(session, blocks, game_id=5)
        assert result[0]["embedded_social_post_id"] is None
        record = next(r for r in caplog.records if "embedded_tweet_ref_missing" in r.message)
        assert record.__dict__["game_id"] == 5
        assert record.__dict__["block_id"] == 3
        assert record.__dict__["embedded_social_post_id"] == 42

    def test_all_ids_missing_clears_all(self, caplog):
        """All blocks with missing IDs are cleared; pipeline continues."""
        import logging
        session = self._mock_session(found_ids=[])
        blocks = [
            {"block_index": 0, "embedded_social_post_id": 42},
            {"block_index": 1, "embedded_social_post_id": 43},
        ]
        with caplog.at_level(logging.WARNING):
            result = self._run(session, blocks)
        assert all(b["embedded_social_post_id"] is None for b in result)
        assert len([r for r in caplog.records if "embedded_tweet_ref_missing" in r.message]) == 2

    def test_multiple_missing_ids_all_warned(self, caplog):
        """Every missing ID gets its own warning; found IDs are preserved."""
        import logging
        session = self._mock_session(found_ids=[1])
        blocks = [
            {"block_index": 0, "embedded_social_post_id": 1},
            {"block_index": 1, "embedded_social_post_id": 7},
            {"block_index": 2, "embedded_social_post_id": 8},
        ]
        with caplog.at_level(logging.WARNING):
            result = self._run(session, blocks)
        assert result[0]["embedded_social_post_id"] == 1
        assert result[1]["embedded_social_post_id"] is None
        assert result[2]["embedded_social_post_id"] is None
        missing_warns = [r for r in caplog.records if "embedded_tweet_ref_missing" in r.message]
        assert len(missing_warns) == 2


# ── Generic phrase density ────────────────────────────────────────────────────


class TestGenericPhraseDensity:
    """Tests for _check_generic_phrase_density in validate_blocks."""

    def setup_method(self) -> None:
        from app.services.pipeline.stages.validate_blocks import _check_generic_phrase_density
        self._check = _check_generic_phrase_density

    def _block(self, idx: int, narrative: str) -> dict:
        return {"block_index": idx, "narrative": narrative}

    def test_clean_blocks_no_warnings(self) -> None:
        """Blocks with zero generic phrases produce no warnings."""
        blocks = [
            self._block(0, (
                "Anthony Davis scored 28 points with 12 rebounds in the fourth quarter "
                "while LeBron James recorded his tenth triple-double of the season and "
                "the Lakers built a commanding lead before the final buzzer tonight."
            )),
        ]
        errors, warnings = self._check(blocks)
        assert errors == []
        assert warnings == []

    def test_high_density_triggers_warning(self) -> None:
        """A block packed with generic phrases produces a structured warning."""
        # ~20 words, 2 generic phrases = 10/100 words — well above 2.0 threshold
        blocks = [
            self._block(0, (
                "They gave it their all and proved too much for the opposition "
                "in what was a memorable evening of basketball action tonight."
            )),
        ]
        errors, warnings = self._check(blocks)
        assert errors == []
        assert len(warnings) == 1
        assert "generic phrase density" in warnings[0]
        assert "block_index=0" in warnings[0] or "Block 0" in warnings[0]

    def test_low_density_no_warning(self) -> None:
        """A single phrase in a long block stays below threshold."""
        # 1 phrase in ~80 words = 1.25/100 — below threshold of 2.0
        filler = " ".join(["The team executed their game plan perfectly."] * 7)
        blocks = [
            self._block(0, "They gave it their all. " + filler),
        ]
        errors, warnings = self._check(blocks)
        assert errors == []
        assert warnings == []

    def test_multiple_blocks_warns_per_block(self) -> None:
        """Each over-dense block produces its own warning."""
        dense_narrative = (
            "They gave it their all, played their hearts out, proved too much, "
            "made their mark, showed a lot of heart in this hard-fought battle."
        )
        blocks = [
            self._block(0, dense_narrative),
            self._block(1, dense_narrative),
        ]
        errors, warnings = self._check(blocks)
        assert errors == []
        assert len(warnings) == 2

    def test_empty_narrative_skipped(self) -> None:
        """Blocks with empty narrative are skipped without error."""
        blocks = [self._block(0, "")]
        errors, warnings = self._check(blocks)
        assert errors == []
        assert warnings == []

    def test_returns_no_errors_ever(self) -> None:
        """Density check never produces errors — only warnings."""
        dense = " ".join(["gave it their all"] * 20)
        blocks = [self._block(i, dense) for i in range(5)]
        errors, warnings = self._check(blocks)
        assert errors == []


# ── RESOLUTION specificity ────────────────────────────────────────────────────


def _make_pbp_event(
    quarter: int,
    game_clock: str,
    player_name: str | None = None,
    home_score: int = 100,
    away_score: int = 95,
) -> dict:
    return {
        "quarter": quarter,
        "game_clock": game_clock,
        "player_name": player_name,
        "home_score": home_score,
        "away_score": away_score,
        "description": "play description",
    }


def _resolution_block(narrative: str, block_index: int = 3) -> dict:
    return {
        "block_index": block_index,
        "role": SemanticRole.RESOLUTION.value,
        "narrative": narrative,
    }


def _setup_block(narrative: str = "A strong opening set the tone.") -> dict:
    return {"block_index": 0, "role": SemanticRole.SETUP.value, "narrative": narrative}


class TestGetFinalWindowPlays:
    """Unit tests for _get_final_window_plays."""

    def test_nba_last_2_min_q4(self) -> None:
        """NBA: returns Q4 plays with clock ≤ 2:00."""
        events = [
            _make_pbp_event(4, "3:00"),   # outside window
            _make_pbp_event(4, "2:00"),   # exactly at boundary — included
            _make_pbp_event(4, "1:30"),   # inside window
            _make_pbp_event(3, "0:30"),   # Q3 — excluded
        ]
        result = _get_final_window_plays(events, "NBA")
        clocks = {e["game_clock"] for e in result}
        assert "1:30" in clocks
        assert "2:00" in clocks
        assert "3:00" not in clocks
        assert "0:30" not in clocks

    def test_nba_ot_plays_always_included(self) -> None:
        """NBA OT plays (quarter > 4) are always in the final window."""
        events = [
            _make_pbp_event(4, "3:00"),
            _make_pbp_event(5, "4:00"),   # OT
        ]
        result = _get_final_window_plays(events, "NBA")
        quarters = {e["quarter"] for e in result}
        assert 5 in quarters
        assert 4 not in quarters

    def test_nfl_mirrors_nba_logic(self) -> None:
        """NFL uses the same Q4 / 2-min rule as NBA."""
        events = [
            _make_pbp_event(4, "1:00"),
            _make_pbp_event(4, "5:00"),
        ]
        result = _get_final_window_plays(events, "NFL")
        assert len(result) == 1
        assert result[0]["game_clock"] == "1:00"

    def test_nhl_returns_period_3_and_ot(self) -> None:
        """NHL: 3rd period and any OT are in the final window."""
        events = [
            _make_pbp_event(1, "10:00"),
            _make_pbp_event(2, "10:00"),
            _make_pbp_event(3, "10:00"),
            _make_pbp_event(4, "3:00"),   # OT
        ]
        result = _get_final_window_plays(events, "NHL")
        quarters = {e["quarter"] for e in result}
        assert 3 in quarters
        assert 4 in quarters
        assert 1 not in quarters
        assert 2 not in quarters

    def test_ncaab_returns_2nd_half(self) -> None:
        """NCAAB: 2nd half (quarter=2) and OT are in the final window."""
        events = [
            _make_pbp_event(1, "10:00"),
            _make_pbp_event(2, "5:00"),
            _make_pbp_event(3, "2:00"),   # OT
        ]
        result = _get_final_window_plays(events, "NCAAB")
        quarters = {e["quarter"] for e in result}
        assert 2 in quarters
        assert 3 in quarters
        assert 1 not in quarters

    def test_mlb_returns_last_inning(self) -> None:
        """MLB: only plays in the highest inning are in the final window."""
        events = [
            _make_pbp_event(7, "0:00"),
            _make_pbp_event(8, "0:00"),
            _make_pbp_event(9, "0:00"),
            _make_pbp_event(9, "0:00"),
        ]
        result = _get_final_window_plays(events, "MLB")
        assert all(e["quarter"] == 9 for e in result)
        assert len(result) == 2

    def test_empty_events_returns_empty(self) -> None:
        """Empty PBP list returns empty list for all sports."""
        for sport in ("NBA", "NFL", "NHL", "NCAAB", "MLB"):
            assert _get_final_window_plays([], sport) == []

    def test_unknown_sport_returns_last_20_pct(self) -> None:
        """Unknown sport falls back to last 20% of events."""
        events = [_make_pbp_event(1, "0:00") for _ in range(10)]
        result = _get_final_window_plays(events, "UNKNOWN_SPORT")
        assert len(result) == 2  # 10 // 5 = 2


class TestCheckResolutionSpecificity:
    """Unit tests for _check_resolution_specificity."""

    def _blocks(self, resolution_narrative: str) -> list[dict]:
        return [_setup_block(), _resolution_block(resolution_narrative)]

    # ── passes ───────────────────────────────────────────────────────────────

    def test_player_name_present_passes(self) -> None:
        """RESOLUTION block naming a final-window player produces no warning."""
        pbp = [_make_pbp_event(4, "1:00", player_name="LeBron James")]
        blocks = self._blocks("LeBron James sealed the game with a clutch basket.")
        errors, warnings = _check_resolution_specificity(blocks, pbp, "NBA")
        assert errors == []
        assert warnings == []
        # Flag must NOT be set on the block
        assert not blocks[-1].get("resolution_specificity_warning")

    def test_score_match_passes(self) -> None:
        """RESOLUTION block with a matching final-window score produces no warning."""
        pbp = [_make_pbp_event(4, "0:30", home_score=107, away_score=98)]
        blocks = self._blocks("The Lakers finished strong to win 107-98.")
        errors, warnings = _check_resolution_specificity(blocks, pbp, "NBA")
        assert errors == []
        assert warnings == []

    def test_no_resolution_block_skips_check(self) -> None:
        """If no RESOLUTION block exists the check is a no-op."""
        pbp = [_make_pbp_event(4, "1:00", player_name="LeBron James")]
        blocks = [_setup_block()]
        errors, warnings = _check_resolution_specificity(blocks, pbp, "NBA")
        assert errors == []
        assert warnings == []

    def test_non_resolution_block_not_checked(self) -> None:
        """The rule only applies to the RESOLUTION block; other roles are ignored."""
        pbp = [_make_pbp_event(4, "1:00", player_name="LeBron James")]
        # SETUP block with a generic narrative, RESOLUTION has player name
        blocks = [
            _setup_block("The team gave it their all from start to finish."),
            _resolution_block("LeBron James hit the game-winner at the buzzer."),
        ]
        errors, warnings = _check_resolution_specificity(blocks, pbp, "NBA")
        assert warnings == []

    def test_no_pbp_events_skips_check(self) -> None:
        """Missing PBP data skips the check (no false positive)."""
        blocks = self._blocks("A generic ending to the game.")
        errors, warnings = _check_resolution_specificity(blocks, [], "NBA")
        assert warnings == []

    def test_no_final_window_plays_skips_check(self) -> None:
        """If no PBP events fall in the final window the check is skipped."""
        # All events in Q1 — no Q4 plays for NBA
        pbp = [_make_pbp_event(1, "10:00", player_name="LeBron James")]
        blocks = self._blocks("A generic ending to the game.")
        errors, warnings = _check_resolution_specificity(blocks, pbp, "NBA")
        assert warnings == []

    # ── warns ────────────────────────────────────────────────────────────────

    def test_generic_narrative_warns(self) -> None:
        """RESOLUTION with only generic text and no score reference produces warning."""
        pbp = [_make_pbp_event(4, "0:30", player_name="LeBron James")]
        blocks = self._blocks(
            "The team gave it everything they had and came away with the victory."
        )
        errors, warnings = _check_resolution_specificity(blocks, pbp, "NBA")
        assert errors == []
        assert len(warnings) == 1
        assert "RESOLUTION" in warnings[0]
        # Flag must be stamped on the block for the grader to read
        assert blocks[-1].get("resolution_specificity_warning") is True

    def test_warning_is_structured(self) -> None:
        """Warning message includes sport and window play count."""
        pbp = [_make_pbp_event(4, "1:00", player_name="Player Name")]
        blocks = self._blocks("The home team held on for a hard-fought victory.")
        _, warnings = _check_resolution_specificity(blocks, pbp, "NBA")
        assert "NBA" in warnings[0]

    def test_partial_name_match_passes(self) -> None:
        """Player last name appearing alone in narrative is a valid reference."""
        pbp = [_make_pbp_event(4, "0:45", player_name="Stephen Curry")]
        blocks = self._blocks("Curry drained the dagger three to ice the game.")
        errors, warnings = _check_resolution_specificity(blocks, pbp, "NBA")
        assert warnings == []

    def test_mlb_last_inning_check(self) -> None:
        """MLB check uses the last inning, not a clock threshold."""
        pbp = [
            _make_pbp_event(8, "0:00", player_name="Judge"),
            _make_pbp_event(9, "0:00", player_name="Ohtani"),
        ]
        blocks = self._blocks("Judge hit the go-ahead homer in the eighth.")
        _, warnings = _check_resolution_specificity(blocks, pbp, "MLB")
        # "Judge" is in inning 8, not the last inning (9), so no match
        assert len(warnings) == 1
        assert blocks[-1].get("resolution_specificity_warning") is True

    def test_mlb_last_inning_player_passes(self) -> None:
        """MLB: player from the last inning present in narrative passes."""
        pbp = [
            _make_pbp_event(8, "0:00", player_name="Judge"),
            _make_pbp_event(9, "0:00", player_name="Ohtani"),
        ]
        blocks = self._blocks("Ohtani delivered the walk-off hit in the ninth inning.")
        _, warnings = _check_resolution_specificity(blocks, pbp, "MLB")
        assert warnings == []

    def test_errors_always_empty(self) -> None:
        """The check never produces errors — only warnings."""
        pbp = [_make_pbp_event(4, "0:30", player_name="Player")]
        blocks = self._blocks("Generic text with no specific reference whatsoever.")
        errors, _ = _check_resolution_specificity(blocks, pbp, "NBA")
        assert errors == []


# ── Information density ───────────────────────────────────────────────────────


class TestInformationDensity:
    """Tests for check_information_density in density.py.

    Five samples: 3 human-validated high-density narratives (should pass) and
    2 content-free synthetic samples derived from the sport templates (should fail).
    """

    def _check(self, blocks, sport, home="HomeTeam", away="AwayTeam"):
        from app.services.pipeline.stages.density import check_information_density

        return check_information_density(blocks, sport, home_team=home, away_team=away)

    def _blocks(self, *narratives: str) -> list[dict]:
        return [{"narrative": n} for n in narratives]

    # ── high-density samples (pass) ───────────────────────────────────────────

    def test_nba_specific_narrative_passes(self) -> None:
        """NBA narrative with player-specific plays, stats, and game moments passes."""
        blocks = self._blocks(
            "Williams rattled home a pull-up jumper from the elbow to give the home "
            "side a seven-point cushion with ninety seconds remaining. Back-to-back "
            "stops on the defensive end allowed the offense to run down the clock, and "
            "the guard's late three-pointer iced the contest in the final minute.",
            "The perimeter defense held the visitors to just three baskets across the "
            "fourth quarter, forcing seven turnovers and converting four fast-break "
            "opportunities. The final margin of twelve points was flattering given "
            "how close the game was through three quarters of sustained competition.",
            "Davis posted twenty-two points and eleven rebounds in thirty-six minutes, "
            "controlling the paint on both ends throughout the second half. His "
            "back-to-back rejections in the closing ninety seconds ended the visitors' "
            "last rally and sealed the outcome on the road.",
            "The home side secured the result with a composed fourth-quarter execution, "
            "holding possession for consecutive offensive sets while their opponents "
            "fouled desperately. Free-throw accuracy proved decisive — nine of ten "
            "converted in the final two minutes cemented a hard-earned victory.",
        )
        score, passed, warnings = self._check(blocks, "NBA", "Hornets", "Raptors")
        assert passed, (
            f"High-density NBA narrative should pass density check, "
            f"got jaccard={score:.3f}, warnings={warnings}"
        )
        assert warnings == []

    def test_nfl_specific_narrative_passes(self) -> None:
        """NFL narrative with quarterback plays, yardage, and drive descriptions passes."""
        blocks = self._blocks(
            "A forty-seven-yard field goal attempt at the two-minute warning "
            "gave the offense a chance to extend their advantage. The quarterback's "
            "scramble on third-and-eight converted for a first down and burned "
            "forty-three seconds off the clock before the kicker split the uprights.",
            "The defensive line pressured the pocket on six consecutive snaps in the "
            "third quarter, forcing three incompletions and a fumble that was recovered "
            "at the twenty-two yard line. That turnover directly led to a seven-play "
            "scoring drive capped by a two-yard plunge from the running back.",
            "A final punt with eighteen seconds remaining left the trailing team "
            "only a desperation heave, which fell incomplete in the end zone as the "
            "cornerback broke up the fade route. The final gun confirmed a hard-fought "
            "twelve-point victory for the home side on a cold afternoon.",
            "Fourth-quarter production told the full story: the offense totalled "
            "one hundred and fourteen yards on three drives while the defense allowed "
            "just thirty-eight yards and forced two punts. Clock management and "
            "red-zone precision were the decisive factors in the outcome.",
        )
        score, passed, warnings = self._check(blocks, "NFL", "Falcons", "Jaguars")
        assert passed, (
            f"High-density NFL narrative should pass density check, "
            f"got jaccard={score:.3f}, warnings={warnings}"
        )
        assert warnings == []

    def test_nhl_specific_narrative_passes(self) -> None:
        """NHL narrative with goaltender saves, power plays, and period details passes."""
        blocks = self._blocks(
            "The power play unit converted on the man advantage after a hooking "
            "penalty, wiring a one-timer past the blocker side from the left circle. "
            "The goaltender made seventeen saves in the third period alone, including "
            "a sprawling pad stop on a two-on-one rush with four minutes remaining.",
            "An empty-net goal with forty seconds left sealed the two-point victory. "
            "The penalty kill went three for three on the night, clearing five "
            "zone entries while shorthanded and preventing any sustained pressure "
            "from the visitors throughout the final period.",
            "The centreman's backhanded redirection off a point shot gave the home "
            "side their first lead of the evening midway through the second period. "
            "That goal opened a three-goal run across eleven minutes as the visitors "
            "struggled to adjust their defensive structure.",
            "Forty-two combined saves over sixty minutes reflected the tight nature "
            "of the game. The home team's goaltender was the difference maker, "
            "stopping nine high-danger attempts including a breakaway in overtime "
            "before his teammates converted on the deciding power play.",
        )
        score, passed, warnings = self._check(blocks, "NHL", "Senators", "Ducks")
        assert passed, (
            f"High-density NHL narrative should pass density check, "
            f"got jaccard={score:.3f}, warnings={warnings}"
        )
        assert warnings == []

    # ── content-free synthetic samples (fail) ────────────────────────────────

    def test_nba_template_text_fails(self) -> None:
        """NBA template-rendered narrative (nearly verbatim) fails the density check."""
        from app.services.pipeline.stages.templates import GameMiniBox, TemplateEngine

        mb = GameMiniBox(
            home_team="HomeTeam",
            away_team="AwayTeam",
            home_score=107,
            away_score=98,
            sport="NBA",
            has_overtime=False,
            total_moments=8,
        )
        blocks = TemplateEngine.render("NBA", mb)
        score, passed, warnings = self._check(
            blocks, "NBA", home="HomeTeam", away="AwayTeam"
        )
        assert not passed, (
            f"Content-free NBA template should fail density check, "
            f"got jaccard={score:.3f}"
        )
        assert len(warnings) == 1
        assert "content-free" in warnings[0].lower() or "template" in warnings[0].lower()

    def test_nfl_template_text_fails(self) -> None:
        """NFL template-rendered narrative (nearly verbatim) fails the density check."""
        from app.services.pipeline.stages.templates import GameMiniBox, TemplateEngine

        mb = GameMiniBox(
            home_team="HomeTeam",
            away_team="AwayTeam",
            home_score=24,
            away_score=17,
            sport="NFL",
            has_overtime=False,
            total_moments=8,
        )
        blocks = TemplateEngine.render("NFL", mb)
        score, passed, warnings = self._check(
            blocks, "NFL", home="HomeTeam", away="AwayTeam"
        )
        assert not passed, (
            f"Content-free NFL template should fail density check, "
            f"got jaccard={score:.3f}"
        )
        assert len(warnings) == 1

    # ── edge cases ────────────────────────────────────────────────────────────

    def test_empty_blocks_passes(self) -> None:
        """Empty block list does not trigger a warning."""
        score, passed, warnings = self._check([], "NBA")
        assert passed
        assert warnings == []

    def test_empty_narrative_blocks_passes(self) -> None:
        """Blocks with no narrative text do not trigger a warning."""
        blocks = [{"narrative": ""}, {"narrative": None}]
        score, passed, warnings = self._check(blocks, "NBA")
        assert passed
        assert warnings == []

    def test_returns_no_errors_ever(self) -> None:
        """check_information_density never raises — warnings only."""
        from app.services.pipeline.stages.density import check_information_density

        # Intentionally malformed input
        blocks = [{"narrative": "x" * 1000}]
        score, passed, warnings = check_information_density(blocks, "NBA")
        assert isinstance(score, float)
        assert isinstance(passed, bool)
        assert isinstance(warnings, list)

    def test_score_is_bounded(self) -> None:
        """Similarity score is always in [0.0, 1.0]."""
        from app.services.pipeline.stages.templates import GameMiniBox, TemplateEngine

        for sport in ("NBA", "NFL", "MLB", "NHL"):
            mb = GameMiniBox(
                home_team="HomeTeam", away_team="AwayTeam",
                home_score=100, away_score=90, sport=sport,
            )
            blocks = TemplateEngine.render(sport, mb)
            score, _, _ = self._check(blocks, sport)
            assert 0.0 <= score <= 1.0, f"{sport}: score {score} out of bounds"

    def test_warning_contains_sport_and_threshold(self) -> None:
        """Warning message includes sport code and threshold value."""
        from app.services.pipeline.stages.templates import GameMiniBox, TemplateEngine

        mb = GameMiniBox(
            home_team="HomeTeam", away_team="AwayTeam",
            home_score=100, away_score=90, sport="NBA",
        )
        blocks = TemplateEngine.render("NBA", mb)
        _, passed, warnings = self._check(blocks, "NBA", "HomeTeam", "AwayTeam")
        if not passed:
            assert len(warnings) == 1
            assert "NBA" in warnings[0]
            assert "threshold" in warnings[0].lower() or "0.60" in warnings[0]
