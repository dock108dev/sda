"""Tests for pipeline models module (v3-summary pipeline)."""


class TestPipelineStage:
    """Tests for PipelineStage enum."""

    def test_ordered_stages(self):
        """ordered_stages returns the four active v3-summary stages in order."""
        from app.services.pipeline.models import PipelineStage

        stages = PipelineStage.ordered_stages()
        assert stages == [
            PipelineStage.NORMALIZE_PBP,
            PipelineStage.CLASSIFY_GAME_SHAPE,
            PipelineStage.GENERATE_SUMMARY,
            PipelineStage.FINALIZE_SUMMARY,
        ]

    def test_next_stage_normal(self):
        """next_stage returns the next active stage."""
        from app.services.pipeline.models import PipelineStage

        assert (
            PipelineStage.NORMALIZE_PBP.next_stage()
            == PipelineStage.CLASSIFY_GAME_SHAPE
        )
        assert (
            PipelineStage.CLASSIFY_GAME_SHAPE.next_stage()
            == PipelineStage.GENERATE_SUMMARY
        )
        assert (
            PipelineStage.GENERATE_SUMMARY.next_stage()
            == PipelineStage.FINALIZE_SUMMARY
        )

    def test_next_stage_last(self):
        """next_stage returns None for the last stage."""
        from app.services.pipeline.models import PipelineStage

        assert PipelineStage.FINALIZE_SUMMARY.next_stage() is None

    def test_previous_stage_first(self):
        """previous_stage returns None for the first stage."""
        from app.services.pipeline.models import PipelineStage

        assert PipelineStage.NORMALIZE_PBP.previous_stage() is None

    def test_legacy_members_parse(self):
        """Legacy stage strings still parse so historical rows load cleanly."""
        from app.services.pipeline.models import PipelineStage

        assert PipelineStage("GENERATE_MOMENTS") == PipelineStage.GENERATE_MOMENTS
        assert PipelineStage("FINALIZE_MOMENTS") == PipelineStage.FINALIZE_MOMENTS


class TestStageInput:
    """Tests for StageInput class."""

    def test_required_fields(self):
        from app.services.pipeline.models import StageInput

        stage_input = StageInput(game_id=123, run_id=456)
        assert stage_input.game_id == 123
        assert stage_input.run_id == 456

    def test_optional_fields_default(self):
        from app.services.pipeline.models import StageInput

        stage_input = StageInput(game_id=123, run_id=456)
        assert stage_input.previous_output is None
        assert stage_input.game_context == {}

    def test_optional_fields_set(self):
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

    def test_add_log_levels(self):
        from app.services.pipeline.models import StageOutput

        output = StageOutput(data={})
        output.add_log("info msg")
        output.add_log("warn msg", level="warning")
        output.add_log("err msg", level="error")

        assert [log["level"] for log in output.logs] == ["info", "warning", "error"]
        assert [log["message"] for log in output.logs] == [
            "info msg",
            "warn msg",
            "err msg",
        ]


class TestNormalizedPBPOutput:
    """Tests for NormalizedPBPOutput class."""

    def test_to_dict_round_trip(self):
        from app.services.pipeline.models import NormalizedPBPOutput

        output = NormalizedPBPOutput(
            pbp_events=[{"play_index": 1}],
            game_start="2026-01-01T00:00:00Z",
            game_end="2026-01-01T03:00:00Z",
            has_overtime=False,
            total_plays=1,
            phase_boundaries={"q1": ("2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z")},
        )
        result = output.to_dict()

        assert result["pbp_events"] == [{"play_index": 1}]
        assert result["total_plays"] == 1
        assert result["has_overtime"] is False
