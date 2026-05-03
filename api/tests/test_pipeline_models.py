"""Tests for pipeline models module."""


class TestPipelineStage:
    """Tests for PipelineStage enum."""

    def test_ordered_stages(self):
        """ordered_stages returns stages in correct order."""
        from app.services.pipeline.models import PipelineStage

        stages = PipelineStage.ordered_stages()
        # 9-stage pipeline: CLASSIFY_GAME_SHAPE -> ANALYZE_DRAMA -> GROUP_BLOCKS
        assert len(stages) == 9
        assert stages[0] == PipelineStage.NORMALIZE_PBP
        assert stages[1] == PipelineStage.GENERATE_MOMENTS
        assert stages[2] == PipelineStage.VALIDATE_MOMENTS
        assert stages[3] == PipelineStage.CLASSIFY_GAME_SHAPE
        assert stages[4] == PipelineStage.ANALYZE_DRAMA
        assert stages[5] == PipelineStage.GROUP_BLOCKS
        assert stages[6] == PipelineStage.RENDER_BLOCKS
        assert stages[7] == PipelineStage.VALIDATE_BLOCKS
        assert stages[8] == PipelineStage.FINALIZE_MOMENTS

    def test_next_stage_normal(self):
        """next_stage returns the next stage."""
        from app.services.pipeline.models import PipelineStage

        assert PipelineStage.NORMALIZE_PBP.next_stage() == PipelineStage.GENERATE_MOMENTS
        assert PipelineStage.GENERATE_MOMENTS.next_stage() == PipelineStage.VALIDATE_MOMENTS

    def test_next_stage_last(self):
        """next_stage returns None for last stage."""
        from app.services.pipeline.models import PipelineStage

        assert PipelineStage.FINALIZE_MOMENTS.next_stage() is None

    def test_previous_stage_normal(self):
        """previous_stage returns the previous stage."""
        from app.services.pipeline.models import PipelineStage

        assert PipelineStage.GENERATE_MOMENTS.previous_stage() == PipelineStage.NORMALIZE_PBP
        # FINALIZE_MOMENTS follows VALIDATE_BLOCKS
        assert PipelineStage.FINALIZE_MOMENTS.previous_stage() == PipelineStage.VALIDATE_BLOCKS

    def test_previous_stage_first(self):
        """previous_stage returns None for first stage."""
        from app.services.pipeline.models import PipelineStage

        assert PipelineStage.NORMALIZE_PBP.previous_stage() is None


class TestStageInput:
    """Tests for StageInput class."""

    def test_required_fields(self):
        """Required fields are set correctly."""
        from app.services.pipeline.models import StageInput

        stage_input = StageInput(game_id=123, run_id=456)
        assert stage_input.game_id == 123
        assert stage_input.run_id == 456

    def test_optional_fields(self):
        """Optional fields have defaults."""
        from app.services.pipeline.models import StageInput

        stage_input = StageInput(game_id=123, run_id=456)
        assert stage_input.previous_output is None
        assert stage_input.game_context == {}

    def test_with_optional_fields(self):
        """Optional fields can be set."""
        from app.services.pipeline.models import StageInput

        stage_input = StageInput(
            game_id=123,
            run_id=456,
            previous_output={"key": "value"},
            game_context={"team": "Lakers"},
        )
        assert stage_input.previous_output == {"key": "value"}
        assert stage_input.game_context == {"team": "Lakers"}


class TestStageOutput:
    """Tests for StageOutput class."""

    def test_add_log_info(self):
        """add_log adds info level logs."""
        from app.services.pipeline.models import StageOutput

        output = StageOutput(data={})
        output.add_log("Test message")

        assert len(output.logs) == 1
        assert output.logs[0]["message"] == "Test message"
        assert output.logs[0]["level"] == "info"

    def test_add_log_warning(self):
        """add_log adds warning level logs."""
        from app.services.pipeline.models import StageOutput

        output = StageOutput(data={})
        output.add_log("Warning message", level="warning")

        assert output.logs[0]["level"] == "warning"

    def test_add_log_error(self):
        """add_log adds error level logs."""
        from app.services.pipeline.models import StageOutput

        output = StageOutput(data={})
        output.add_log("Error message", level="error")

        assert output.logs[0]["level"] == "error"


class TestGeneratedMomentsOutput:
    """Tests for GeneratedMomentsOutput class."""

    def test_to_dict_minimal(self):
        """to_dict with minimal fields."""
        from app.services.pipeline.models import GeneratedMomentsOutput

        output = GeneratedMomentsOutput(
            moments=[{"id": 1}],
            notable_moments=[],
            moment_count=1,
            budget=100,
            within_budget=True,
        )
        result = output.to_dict()

        assert result["moments"] == [{"id": 1}]
        assert result["moment_count"] == 1
        assert result["within_budget"] is True
        assert "generation_trace" not in result
        assert "moment_distribution" not in result

    def test_to_dict_with_trace(self):
        """to_dict includes generation trace when present."""
        from app.services.pipeline.models import GeneratedMomentsOutput

        output = GeneratedMomentsOutput(
            moments=[],
            notable_moments=[],
            moment_count=0,
            budget=100,
            within_budget=True,
            generation_trace={"key": "value"},
        )
        result = output.to_dict()

        assert result["generation_trace"] == {"key": "value"}

    def test_to_dict_with_distribution(self):
        """to_dict includes moment distribution when present."""
        from app.services.pipeline.models import GeneratedMomentsOutput

        output = GeneratedMomentsOutput(
            moments=[],
            notable_moments=[],
            moment_count=0,
            budget=100,
            within_budget=True,
            moment_distribution={"phase_1": 5, "phase_2": 10},
        )
        result = output.to_dict()

        assert result["moment_distribution"] == {"phase_1": 5, "phase_2": 10}


class TestQualityStatus:
    """Tests for QualityStatus enum."""

    def test_values(self):
        """Enum has expected values."""
        from app.services.pipeline.models import QualityStatus

        assert QualityStatus.PASSED.value == "PASSED"
        assert QualityStatus.DEGRADED.value == "DEGRADED"
        assert QualityStatus.FAILED.value == "FAILED"
        assert QualityStatus.OVERRIDDEN.value == "OVERRIDDEN"


class TestScoreContinuityOverride:
    """Tests for ScoreContinuityOverride class."""

    def test_default_values(self):
        """Default values are set correctly."""
        from app.services.pipeline.models import ScoreContinuityOverride

        override = ScoreContinuityOverride()

        assert override.enabled is False
        assert override.reason is None
        assert override.overridden_by is None
        assert override.overridden_at is None

    def test_to_dict(self):
        """to_dict returns all fields."""
        from app.services.pipeline.models import ScoreContinuityOverride

        override = ScoreContinuityOverride(
            enabled=True,
            reason="Manual fix",
            overridden_by="admin",
            overridden_at="2026-01-15T10:00:00Z",
        )
        result = override.to_dict()

        assert result["enabled"] is True
        assert result["reason"] == "Manual fix"
        assert result["overridden_by"] == "admin"
        assert result["overridden_at"] == "2026-01-15T10:00:00Z"


class TestValidationOutput:
    """Tests for ValidationOutput class."""

    def test_to_dict_minimal(self):
        """to_dict with minimal fields."""
        from app.services.pipeline.models import ValidationOutput

        output = ValidationOutput(
            passed=True,
            critical_passed=True,
            warnings_count=0,
            errors=[],
            warnings=[],
            validation_details={},
        )
        result = output.to_dict()

        assert result["passed"] is True
        assert result["quality_status"] == "PASSED"
        assert "score_continuity_override" not in result

    def test_to_dict_with_override(self):
        """to_dict includes override when present."""
        from app.services.pipeline.models import (
            ScoreContinuityOverride,
            ValidationOutput,
        )

        override = ScoreContinuityOverride(enabled=True, reason="Test")
        output = ValidationOutput(
            passed=True,
            critical_passed=True,
            warnings_count=0,
            errors=[],
            warnings=[],
            validation_details={},
            score_continuity_override=override,
        )
        result = output.to_dict()

        assert "score_continuity_override" in result
        assert result["score_continuity_override"]["enabled"] is True


class TestFinalizedOutput:
    """Tests for FinalizedOutput class."""

    def test_to_dict_minimal(self):
        """to_dict with minimal fields."""
        from app.services.pipeline.models import FinalizedOutput

        output = FinalizedOutput(
            artifact_id=123,
            timeline_events=50,
            moment_count=10,
            generated_at="2026-01-15T10:00:00Z",
        )
        result = output.to_dict()

        assert result["artifact_id"] == 123
        assert result["timeline_events"] == 50
        assert result["moment_count"] == 10
        assert result["quality_status"] == "PASSED"
        assert "moment_distribution" not in result

    def test_to_dict_with_distribution(self):
        """to_dict includes distribution when present."""
        from app.services.pipeline.models import FinalizedOutput

        output = FinalizedOutput(
            artifact_id=123,
            timeline_events=50,
            moment_count=10,
            generated_at="2026-01-15T10:00:00Z",
            moment_distribution={"key": "value"},
        )
        result = output.to_dict()

        assert result["moment_distribution"] == {"key": "value"}
