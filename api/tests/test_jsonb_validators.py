"""Tests for JSONB schema validation — registry, event hooks, and typed errors.

Covers:
- JsonbValidationError attributes (column_name, field_path)
- ExternalIdsSchema: accepts valid, rejects bool/nested/non-dict
- DictJsonSchema: accepts any object, rejects arrays/scalars
- ListOfDictsSchema: accepts list-of-dicts, rejects plain dicts/scalars
- MomentsJsonSchema: requires play_ids on each item
- BlocksJsonSchema: requires block_index, role (enum), narrative
- PipelineLogsJsonSchema: requires timestamp, level (enum), message
- validate_jsonb_column: delegates to registry, no-ops for unknown columns
- external_id_validators: mapper hooks raise JsonbValidationError on bad data
- jsonb_validators: hooks for boxscore, play, flow, timeline, pipeline-stage models
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.db.jsonb_registry import (
    BlocksJsonSchema,
    DictJsonSchema,
    ExternalIdsSchema,
    JsonbValidationError,
    ListOfDictsSchema,
    MomentsJsonSchema,
    PipelineLogsJsonSchema,
    validate_jsonb_column,
)

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_VALID_MOMENT = {
    "play_ids": [0, 1, 2],
    "explicitly_narrated_play_ids": [1],
    "period": 1,
    "start_clock": "12:00",
    "end_clock": "9:43",
    "score_before": [0, 0],
    "score_after": [3, 2],
}

_VALID_BLOCK = {
    "block_index": 0,
    "role": "SETUP",
    "narrative": "The Lakers jumped out to an early lead.",
    "moment_indices": [0, 1],
    "play_ids": [0, 1, 2, 3],
    "key_play_ids": [1],
    "period_start": 1,
    "period_end": 1,
    "score_before": [0, 0],
    "score_after": [14, 10],
    "mini_box": {
        "cumulative": {"home": {"points": 14}, "away": {"points": 10}},
        "delta": {"home": {"points": 14}, "away": {"points": 10}},
    },
    "peak_margin": 6,
    "peak_leader": 1,
    "embedded_social_post_id": None,
}

_VALID_LOG_ENTRY = {
    "timestamp": "2026-04-20T12:00:00+00:00",
    "level": "info",
    "message": "Stage started",
}


# ---------------------------------------------------------------------------
# JsonbValidationError
# ---------------------------------------------------------------------------


class TestJsonbValidationError:
    def test_is_value_error(self):
        exc = JsonbValidationError("col", "bad")
        assert isinstance(exc, ValueError)

    def test_column_name_attribute(self):
        exc = JsonbValidationError("sports_games.external_ids", "bad value")
        assert exc.column_name == "sports_games.external_ids"

    def test_field_path_attribute(self):
        exc = JsonbValidationError("col", "msg", field_path="key.nested")
        assert exc.field_path == "key.nested"

    def test_message_contains_column_name(self):
        exc = JsonbValidationError("my_col", "bad value")
        assert "my_col" in str(exc)

    def test_default_field_path_empty(self):
        exc = JsonbValidationError("col", "msg")
        assert exc.field_path == ""


# ---------------------------------------------------------------------------
# ExternalIdsSchema
# ---------------------------------------------------------------------------


class TestExternalIdsSchema:
    def test_accepts_valid_flat_dict(self):
        ExternalIdsSchema.model_validate({"nba_game_id": "0022400123", "espn_id": 12345})

    def test_accepts_empty_dict(self):
        ExternalIdsSchema.model_validate({})

    def test_rejects_non_dict(self):
        with pytest.raises(Exception):
            ExternalIdsSchema.model_validate([1, 2, 3])

    def test_rejects_nested_object(self):
        with pytest.raises(Exception):
            ExternalIdsSchema.model_validate({"key": {"nested": "value"}})

    def test_rejects_boolean_value(self):
        with pytest.raises(Exception):
            ExternalIdsSchema.model_validate({"key": True})

    def test_rejects_null_value(self):
        with pytest.raises(Exception):
            ExternalIdsSchema.model_validate({"key": None})

    def test_rejects_list_value(self):
        with pytest.raises(Exception):
            ExternalIdsSchema.model_validate({"key": ["a", "b"]})

    def test_accepts_int_value(self):
        ExternalIdsSchema.model_validate({"cbb_team_id": 5678})

    def test_accepts_string_value(self):
        ExternalIdsSchema.model_validate({"odds_api_event_id": "evt_abc"})


# ---------------------------------------------------------------------------
# DictJsonSchema
# ---------------------------------------------------------------------------


class TestDictJsonSchema:
    def test_accepts_any_object(self):
        DictJsonSchema.model_validate({"key": "value", "nested": {"a": 1}})

    def test_accepts_empty_object(self):
        DictJsonSchema.model_validate({})

    def test_rejects_list(self):
        with pytest.raises(Exception):
            DictJsonSchema.model_validate([{"a": 1}])

    def test_rejects_string(self):
        with pytest.raises(Exception):
            DictJsonSchema.model_validate("not a dict")

    def test_rejects_integer(self):
        with pytest.raises(Exception):
            DictJsonSchema.model_validate(42)


# ---------------------------------------------------------------------------
# ListOfDictsSchema
# ---------------------------------------------------------------------------


class TestListOfDictsSchema:
    def test_accepts_list_of_dicts(self):
        ListOfDictsSchema.model_validate([{"type": "score", "value": 3}])

    def test_accepts_empty_list(self):
        ListOfDictsSchema.model_validate([])

    def test_rejects_plain_dict(self):
        with pytest.raises(Exception):
            ListOfDictsSchema.model_validate({"key": "value"})

    def test_rejects_string(self):
        with pytest.raises(Exception):
            ListOfDictsSchema.model_validate("not a list")

    def test_rejects_list_of_scalars(self):
        with pytest.raises(Exception):
            ListOfDictsSchema.model_validate([1, 2, 3])


# ---------------------------------------------------------------------------
# MomentsJsonSchema
# ---------------------------------------------------------------------------


class TestMomentsJsonSchema:
    def test_accepts_valid_moment(self):
        MomentsJsonSchema.model_validate([_VALID_MOMENT])

    def test_accepts_empty_list(self):
        MomentsJsonSchema.model_validate([])

    def test_accepts_minimal_moment_only_play_ids(self):
        MomentsJsonSchema.model_validate([{"play_ids": [0, 1]}])

    def test_accepts_extra_fields(self):
        # extra: "allow" — unknown keys should not raise
        MomentsJsonSchema.model_validate([{**_VALID_MOMENT, "custom_field": "ok"}])

    def test_rejects_missing_play_ids(self):
        with pytest.raises(Exception):
            MomentsJsonSchema.model_validate([{"period": 1}])

    def test_rejects_non_integer_play_ids(self):
        with pytest.raises(Exception):
            MomentsJsonSchema.model_validate([{"play_ids": ["a", "b"]}])

    def test_rejects_plain_dict(self):
        with pytest.raises(Exception):
            MomentsJsonSchema.model_validate({"play_ids": [0]})

    def test_rejects_list_of_scalars(self):
        with pytest.raises(Exception):
            MomentsJsonSchema.model_validate([1, 2, 3])

    def test_validates_multiple_moments(self):
        moments = [
            {"play_ids": [0, 1], "period": 1},
            {"play_ids": [2, 3], "period": 1},
            {"play_ids": [4], "period": 2},
        ]
        MomentsJsonSchema.model_validate(moments)

    def test_rejects_moment_with_bad_play_ids_type(self):
        with pytest.raises(Exception):
            MomentsJsonSchema.model_validate([{"play_ids": "not_a_list"}])


# ---------------------------------------------------------------------------
# BlocksJsonSchema
# ---------------------------------------------------------------------------


class TestBlocksJsonSchema:
    def test_accepts_valid_block(self):
        BlocksJsonSchema.model_validate([_VALID_BLOCK])

    def test_accepts_empty_list(self):
        BlocksJsonSchema.model_validate([])

    def test_accepts_minimal_block(self):
        BlocksJsonSchema.model_validate([
            {"block_index": 0, "role": "SETUP", "narrative": "Game started."}
        ])

    def test_accepts_all_roles(self):
        roles = ["SETUP", "MOMENTUM_SHIFT", "RESPONSE", "DECISION_POINT", "RESOLUTION"]
        for i, role in enumerate(roles):
            BlocksJsonSchema.model_validate([
                {"block_index": i, "role": role, "narrative": f"{role} narrative."}
            ])

    def test_rejects_unknown_role(self):
        with pytest.raises(Exception):
            BlocksJsonSchema.model_validate([
                {"block_index": 0, "role": "UNKNOWN_ROLE", "narrative": "text"}
            ])

    def test_rejects_missing_narrative(self):
        with pytest.raises(Exception):
            BlocksJsonSchema.model_validate([
                {"block_index": 0, "role": "SETUP"}
            ])

    def test_rejects_empty_narrative(self):
        with pytest.raises(Exception):
            BlocksJsonSchema.model_validate([
                {"block_index": 0, "role": "SETUP", "narrative": ""}
            ])

    def test_rejects_missing_block_index(self):
        with pytest.raises(Exception):
            BlocksJsonSchema.model_validate([
                {"role": "SETUP", "narrative": "text"}
            ])

    def test_rejects_negative_block_index(self):
        with pytest.raises(Exception):
            BlocksJsonSchema.model_validate([
                {"block_index": -1, "role": "SETUP", "narrative": "text"}
            ])

    def test_rejects_plain_dict(self):
        with pytest.raises(Exception):
            BlocksJsonSchema.model_validate({"block_index": 0, "role": "SETUP", "narrative": "x"})

    def test_accepts_extra_fields(self):
        BlocksJsonSchema.model_validate([{**_VALID_BLOCK, "extra_key": "allowed"}])


# ---------------------------------------------------------------------------
# PipelineLogsJsonSchema
# ---------------------------------------------------------------------------


class TestPipelineLogsJsonSchema:
    def test_accepts_valid_log_entry(self):
        PipelineLogsJsonSchema.model_validate([_VALID_LOG_ENTRY])

    def test_accepts_empty_list(self):
        PipelineLogsJsonSchema.model_validate([])

    def test_accepts_all_valid_levels(self):
        for level in ("info", "warning", "error", "debug"):
            PipelineLogsJsonSchema.model_validate([
                {"timestamp": "2026-04-20T00:00:00Z", "level": level, "message": "test"}
            ])

    def test_rejects_invalid_level(self):
        with pytest.raises(Exception):
            PipelineLogsJsonSchema.model_validate([
                {"timestamp": "2026-04-20T00:00:00Z", "level": "CRITICAL", "message": "bad"}
            ])

    def test_rejects_missing_timestamp(self):
        with pytest.raises(Exception):
            PipelineLogsJsonSchema.model_validate([
                {"level": "info", "message": "no timestamp"}
            ])

    def test_rejects_missing_message(self):
        with pytest.raises(Exception):
            PipelineLogsJsonSchema.model_validate([
                {"timestamp": "2026-04-20T00:00:00Z", "level": "info"}
            ])

    def test_rejects_empty_message(self):
        with pytest.raises(Exception):
            PipelineLogsJsonSchema.model_validate([
                {"timestamp": "2026-04-20T00:00:00Z", "level": "info", "message": ""}
            ])

    def test_rejects_plain_dict(self):
        with pytest.raises(Exception):
            PipelineLogsJsonSchema.model_validate(_VALID_LOG_ENTRY)

    def test_accepts_extra_fields(self):
        PipelineLogsJsonSchema.model_validate([{**_VALID_LOG_ENTRY, "extra": "ok"}])


# ---------------------------------------------------------------------------
# validate_jsonb_column
# ---------------------------------------------------------------------------


class TestValidateJsonbColumn:
    def test_known_column_valid(self):
        validate_jsonb_column("sports_games", "external_ids", {"espn_id": "123"})

    def test_known_column_invalid_raises(self):
        with pytest.raises(JsonbValidationError) as exc_info:
            validate_jsonb_column("sports_games", "external_ids", "not a dict")
        assert exc_info.value.column_name == "external_ids"

    def test_unknown_table_is_noop(self):
        validate_jsonb_column("unknown_table", "some_col", "anything")

    def test_unknown_column_is_noop(self):
        validate_jsonb_column("sports_games", "nonexistent_col", [1, 2, 3])

    def test_none_value_is_noop(self):
        validate_jsonb_column("sports_games", "external_ids", None)

    def test_raw_stats_json_accepts_object(self):
        validate_jsonb_column(
            "sports_team_boxscores", "raw_stats_json", {"fg": 8, "fga": 15}
        )

    def test_raw_stats_json_rejects_array(self):
        with pytest.raises(JsonbValidationError):
            validate_jsonb_column("sports_team_boxscores", "raw_stats_json", [1, 2])

    def test_moments_json_accepts_valid_moment(self):
        validate_jsonb_column(
            "sports_game_stories",
            "moments_json",
            [_VALID_MOMENT],
        )

    def test_moments_json_rejects_missing_play_ids(self):
        with pytest.raises(JsonbValidationError):
            validate_jsonb_column(
                "sports_game_stories",
                "moments_json",
                [{"period": 1}],
            )

    def test_moments_json_rejects_dict(self):
        with pytest.raises(JsonbValidationError):
            validate_jsonb_column(
                "sports_game_stories", "moments_json", {"play_ids": [0]}
            )

    def test_blocks_json_accepts_valid_block(self):
        validate_jsonb_column(
            "sports_game_stories",
            "blocks_json",
            [_VALID_BLOCK],
        )

    def test_blocks_json_rejects_unknown_role(self):
        bad_block = {**_VALID_BLOCK, "role": "FAKE_ROLE"}
        with pytest.raises(JsonbValidationError):
            validate_jsonb_column("sports_game_stories", "blocks_json", [bad_block])

    def test_pipeline_stage_output_json_accepts_object(self):
        validate_jsonb_column(
            "sports_game_pipeline_stages",
            "output_json",
            {"finalized": True, "flow_id": 42},
        )

    def test_pipeline_stage_output_json_rejects_array(self):
        with pytest.raises(JsonbValidationError):
            validate_jsonb_column(
                "sports_game_pipeline_stages", "output_json", [1, 2, 3]
            )

    def test_pipeline_stage_logs_json_accepts_valid_logs(self):
        validate_jsonb_column(
            "sports_game_pipeline_stages",
            "logs_json",
            [_VALID_LOG_ENTRY],
        )

    def test_pipeline_stage_logs_json_rejects_invalid_level(self):
        bad_log = {**_VALID_LOG_ENTRY, "level": "CRITICAL"}
        with pytest.raises(JsonbValidationError):
            validate_jsonb_column(
                "sports_game_pipeline_stages", "logs_json", [bad_log]
            )

    def test_pipeline_stage_logs_json_rejects_plain_dict(self):
        with pytest.raises(JsonbValidationError):
            validate_jsonb_column(
                "sports_game_pipeline_stages", "logs_json", _VALID_LOG_ENTRY
            )

    def test_timeline_json_accepts_list(self):
        validate_jsonb_column(
            "sports_game_timeline_artifacts",
            "timeline_json",
            [{"t": 0, "event": "tip_off"}],
        )

    def test_game_analysis_json_accepts_object(self):
        validate_jsonb_column(
            "sports_game_timeline_artifacts",
            "game_analysis_json",
            {"drama_score": 0.8, "winner": "home"},
        )

    def test_summary_json_rejects_array(self):
        with pytest.raises(JsonbValidationError):
            validate_jsonb_column(
                "sports_game_timeline_artifacts", "summary_json", ["item1"]
            )


# ---------------------------------------------------------------------------
# external_id_validators mapper hooks
# ---------------------------------------------------------------------------


class TestExternalIdValidatorHooks:
    """Mapper event hooks raise JsonbValidationError for bad payloads."""

    def _fire_game_hook(self, external_ids):
        from app.db import external_id_validators  # noqa: F401 — ensure registered
        from app.db.external_id_validators import _validate_game_external_ids
        from app.db.sports import SportsGame

        target = MagicMock(spec=SportsGame)
        target.external_ids = external_ids
        _validate_game_external_ids(None, None, target)

    def _fire_team_hook(self, external_codes):
        from app.db.external_id_validators import _validate_team_external_codes
        from app.db.sports import SportsTeam

        target = MagicMock(spec=SportsTeam)
        target.external_codes = external_codes
        _validate_team_external_codes(None, None, target)

    def test_game_valid_external_ids(self):
        self._fire_game_hook({"espn_game_id": "12345", "nba_game_id": "0022400001"})

    def test_game_invalid_bool_value_raises(self):
        with pytest.raises(JsonbValidationError) as exc_info:
            self._fire_game_hook({"flag": True})
        assert "external_ids" in exc_info.value.column_name.lower()

    def test_game_invalid_nested_dict_raises(self):
        with pytest.raises(JsonbValidationError):
            self._fire_game_hook({"key": {"nested": "value"}})

    def test_game_none_external_ids_skipped(self):
        self._fire_game_hook(None)  # Should not raise

    def test_team_valid_external_codes(self):
        self._fire_team_hook({"cbb_team_id": 1234})

    def test_team_invalid_raises(self):
        with pytest.raises(JsonbValidationError):
            self._fire_team_hook({"key": [1, 2, 3]})


# ---------------------------------------------------------------------------
# jsonb_validators mapper hooks
# ---------------------------------------------------------------------------


class TestJsonbValidatorHooks:
    """Smoke tests for each mapper hook in jsonb_validators."""

    def test_team_boxscore_valid_stats(self):
        from app.db.jsonb_validators import _validate_team_boxscore_stats
        from app.db.sports import SportsTeamBoxscore

        target = MagicMock(spec=SportsTeamBoxscore)
        target.stats = {"fg": 8, "fga": 20, "pts": 18}
        _validate_team_boxscore_stats(None, None, target)

    def test_team_boxscore_invalid_stats_raises(self):
        from app.db.jsonb_validators import _validate_team_boxscore_stats
        from app.db.sports import SportsTeamBoxscore

        target = MagicMock(spec=SportsTeamBoxscore)
        target.stats = ["not", "an", "object"]
        with pytest.raises(JsonbValidationError):
            _validate_team_boxscore_stats(None, None, target)

    def test_play_raw_data_valid(self):
        from app.db.jsonb_validators import _validate_play_raw_data
        from app.db.sports import SportsGamePlay

        target = MagicMock(spec=SportsGamePlay)
        target.raw_data = {"is_home_team": True, "shot_type": "layup"}
        _validate_play_raw_data(None, None, target)

    def test_play_raw_data_invalid_raises(self):
        from app.db.jsonb_validators import _validate_play_raw_data
        from app.db.sports import SportsGamePlay

        target = MagicMock(spec=SportsGamePlay)
        target.raw_data = "raw string"
        with pytest.raises(JsonbValidationError):
            _validate_play_raw_data(None, None, target)

    def test_game_flow_valid(self):
        from app.db.flow import SportsGameFlow
        from app.db.jsonb_validators import _validate_game_flow

        target = MagicMock(spec=SportsGameFlow)
        target.moments_json = [_VALID_MOMENT]
        target.blocks_json = [_VALID_BLOCK]
        _validate_game_flow(None, None, target)

    def test_game_flow_invalid_blocks_raises(self):
        from app.db.flow import SportsGameFlow
        from app.db.jsonb_validators import _validate_game_flow

        target = MagicMock(spec=SportsGameFlow)
        target.moments_json = None
        target.blocks_json = {"not": "a list"}
        with pytest.raises(JsonbValidationError):
            _validate_game_flow(None, None, target)

    def test_game_flow_blocks_invalid_role_raises(self):
        from app.db.flow import SportsGameFlow
        from app.db.jsonb_validators import _validate_game_flow

        target = MagicMock(spec=SportsGameFlow)
        target.moments_json = None
        target.blocks_json = [{**_VALID_BLOCK, "role": "NOT_A_ROLE"}]
        with pytest.raises(JsonbValidationError):
            _validate_game_flow(None, None, target)

    def test_timeline_artifact_valid(self):
        from app.db.flow import SportsGameTimelineArtifact
        from app.db.jsonb_validators import _validate_timeline_artifact

        target = MagicMock(spec=SportsGameTimelineArtifact)
        target.timeline_json = [{"t": 0}]
        target.game_analysis_json = {"drama": 0.9}
        target.summary_json = {"winner": "home"}
        _validate_timeline_artifact(None, None, target)

    def test_timeline_artifact_invalid_summary_raises(self):
        from app.db.flow import SportsGameTimelineArtifact
        from app.db.jsonb_validators import _validate_timeline_artifact

        target = MagicMock(spec=SportsGameTimelineArtifact)
        target.timeline_json = []
        target.game_analysis_json = {}
        target.summary_json = ["not", "a", "dict"]
        with pytest.raises(JsonbValidationError):
            _validate_timeline_artifact(None, None, target)

    def test_pipeline_stage_valid(self):
        from app.db.jsonb_validators import _validate_pipeline_stage
        from app.db.pipeline import GamePipelineStage

        target = MagicMock(spec=GamePipelineStage)
        target.output_json = {"finalized": True, "flow_id": 1}
        target.logs_json = [_VALID_LOG_ENTRY]
        _validate_pipeline_stage(None, None, target)

    def test_pipeline_stage_output_array_raises(self):
        from app.db.jsonb_validators import _validate_pipeline_stage
        from app.db.pipeline import GamePipelineStage

        target = MagicMock(spec=GamePipelineStage)
        target.output_json = [1, 2, 3]
        target.logs_json = []
        with pytest.raises(JsonbValidationError):
            _validate_pipeline_stage(None, None, target)

    def test_pipeline_stage_invalid_log_level_raises(self):
        from app.db.jsonb_validators import _validate_pipeline_stage
        from app.db.pipeline import GamePipelineStage

        target = MagicMock(spec=GamePipelineStage)
        target.output_json = None
        target.logs_json = [
            {"timestamp": "2026-04-20T00:00:00Z", "level": "TRACE", "message": "bad"}
        ]
        with pytest.raises(JsonbValidationError):
            _validate_pipeline_stage(None, None, target)

    def test_pipeline_stage_none_output_is_noop(self):
        from app.db.jsonb_validators import _validate_pipeline_stage
        from app.db.pipeline import GamePipelineStage

        target = MagicMock(spec=GamePipelineStage)
        target.output_json = None
        target.logs_json = []
        _validate_pipeline_stage(None, None, target)  # Should not raise
