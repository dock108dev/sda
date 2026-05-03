"""Tests for the structured pipeline debug logger.

Covers the FlowDebugLogger contract: per-game accumulation of source-data
metrics, boundary decisions (selected and rejected with reasons), prompt
payload SHA, generation result (PUBLISH/REGENERATE/FALLBACK with explicit
fallback reason), validation status, persist/skip decision, and the NHL
DEBUG record fields.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from app.services.pipeline.helpers.flow_debug_logger import (
    FlowDebugLogger,
    get_logger,
    get_or_create_logger,
    pop_logger,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    reset_for_tests()
    yield
    reset_for_tests()


class TestFlowDebugLoggerAccumulation:
    """Verify each kind of recorded field round-trips through to_payload()."""

    def test_data_metrics_recorded(self):
        log = FlowDebugLogger(game_id=123, league="NBA")
        log.record_data_metrics(
            source_play_count=400, scoring_event_count=120, lead_change_count=8
        )
        payload = log.to_payload()
        assert payload["source_play_count"] == 400
        assert payload["scoring_event_count"] == 120
        assert payload["lead_change_count"] == 8

    def test_archetype_recorded(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_archetype("comeback")
        assert log.to_payload()["selected_archetype"] == "comeback"

    def test_selected_boundary_carries_trigger_reason(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_boundary(moment_index=12, trigger="lead_change", priority=1)
        log.record_boundary(moment_index=58, trigger="scoring_run", priority=3)
        payload = log.to_payload()
        assert payload["selected_boundaries"] == [
            {"moment_index": 12, "trigger": "lead_change", "priority": 1},
            {"moment_index": 58, "trigger": "scoring_run", "priority": 3},
        ]

    def test_rejected_boundary_carries_reason(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_rejected_boundary(
            moment_index=42, reason="period_boundary_no_state_change"
        )
        payload = log.to_payload()
        assert payload["rejected_boundaries"] == [
            {"moment_index": 42, "reason": "period_boundary_no_state_change"}
        ]

    def test_validation_result_recorded(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_validation_result(
            status="failed",
            warnings=["density warning"],
            errors=["banned phrase: clutch"],
        )
        payload = log.to_payload()
        assert payload["validation_status"] == "failed"
        assert payload["validation_warnings"] == ["density warning"]
        assert payload["validation_errors"] == ["banned phrase: clutch"]

    def test_persist_decision_with_skip_reason(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_persist_decision(persisted=False, skip_reason="score_mismatch_pre_write")
        payload = log.to_payload()
        assert payload["persisted"] is False
        assert payload["skip_reason"] == "score_mismatch_pre_write"

    def test_persisted_true_clears_skip_reason(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_persist_decision(persisted=True)
        payload = log.to_payload()
        assert payload["persisted"] is True
        assert payload["skip_reason"] is None


class TestGenerationResult:
    """PUBLISH/REGENERATE/FALLBACK + explicit fallback reason for FALLBACK."""

    def test_publish_does_not_record_fallback_reason(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_generation_result("PUBLISH")
        payload = log.to_payload()
        assert payload["generation_result"] == "PUBLISH"
        assert payload["fallback_reason"] is None

    def test_regenerate_does_not_record_fallback_reason(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_generation_result("REGENERATE")
        payload = log.to_payload()
        assert payload["generation_result"] == "REGENERATE"
        assert payload["fallback_reason"] is None

    def test_fallback_records_reason(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_generation_result("FALLBACK", fallback_reason="coverage_fail")
        payload = log.to_payload()
        assert payload["generation_result"] == "FALLBACK"
        assert payload["fallback_reason"] == "coverage_fail"

    def test_fallback_without_reason_falls_back_to_unspecified(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        log.record_generation_result("FALLBACK")
        assert log.to_payload()["fallback_reason"] == "unspecified"


class TestPromptPayloadHash:
    """Prompt SHA is recorded; payload is saved only when env flag is set."""

    def test_string_prompt_hash_is_sha256(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        prompt = "hello world"
        digest = log.record_prompt_payload(prompt)
        expected = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        assert digest == expected
        assert log.to_payload()["prompt_payload_hash"] == expected

    def test_object_prompt_hash_is_canonical(self):
        log = FlowDebugLogger(game_id=1, league="NBA")
        digest = log.record_prompt_payload({"b": 2, "a": 1})
        # Canonical form sorts keys, so {"a":1,"b":2} and {"b":2,"a":1} hash equal
        canonical = json.dumps({"a": 1, "b": 2}, sort_keys=True, default=str)
        assert digest == hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def test_save_disabled_does_not_write_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLOW_DEBUG_SAVE", raising=False)
        monkeypatch.setenv("FLOW_DEBUG_SAVE_DIR", str(tmp_path))
        log = FlowDebugLogger(game_id=99, league="NBA")
        log.record_prompt_payload("prompt body")
        assert list(tmp_path.iterdir()) == []
        assert log.prompt_payload_path is None

    def test_save_enabled_writes_payload_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLOW_DEBUG_SAVE", "true")
        monkeypatch.setenv("FLOW_DEBUG_SAVE_DIR", str(tmp_path))
        log = FlowDebugLogger(game_id=99, league="NBA")
        log.record_prompt_payload("prompt body")
        target = Path(tmp_path) / "flow_99.json"
        assert target.exists()
        envelope = json.loads(target.read_text())
        assert envelope["game_id"] == 99
        assert envelope["league"] == "NBA"
        assert envelope["payload_text"] == "prompt body"
        assert log.prompt_payload_path == str(target)


class TestNHLDebugRecord:
    """NHL-specific DEBUG fields populate from accumulated state on emit."""

    def test_nhl_emit_logs_debug_record(self, caplog):
        log = FlowDebugLogger(game_id=42, league="NHL")
        log.record_data_metrics(source_play_count=200, scoring_event_count=5)
        log.record_persist_decision(persisted=True)
        with caplog.at_level(logging.DEBUG, logger="app.services.pipeline.helpers.flow_debug_logger"):
            log.emit()
        nhl_records = [r for r in caplog.records if r.message == "flow_pipeline_nhl_debug"]
        assert len(nhl_records) == 1
        nhl = nhl_records[0]
        assert nhl.game_id == 42
        assert nhl.was_considered is True
        assert nhl.pbp_exists is True
        assert nhl.goals_found == 5
        assert nhl.flow_attempted is True
        assert nhl.failure_reason is None

    def test_nhl_failure_reason_inferred_from_skip(self, caplog):
        log = FlowDebugLogger(game_id=42, league="NHL")
        log.record_data_metrics(source_play_count=0, scoring_event_count=0)
        log.record_persist_decision(persisted=False, skip_reason="score_mismatch_pre_write")
        with caplog.at_level(logging.DEBUG, logger="app.services.pipeline.helpers.flow_debug_logger"):
            log.emit()
        nhl_records = [r for r in caplog.records if r.message == "flow_pipeline_nhl_debug"]
        assert nhl_records[0].failure_reason == "score_mismatch_pre_write"
        assert nhl_records[0].pbp_exists is False
        assert nhl_records[0].goals_found == 0

    def test_non_nhl_does_not_emit_nhl_debug(self, caplog):
        log = FlowDebugLogger(game_id=42, league="NBA")
        with caplog.at_level(logging.DEBUG, logger="app.services.pipeline.helpers.flow_debug_logger"):
            log.emit()
        nhl_records = [r for r in caplog.records if r.message == "flow_pipeline_nhl_debug"]
        assert nhl_records == []

    def test_explicit_nhl_state_wins_over_inference(self, caplog):
        log = FlowDebugLogger(game_id=7, league="NHL")
        log.record_nhl_state(
            was_considered=True,
            pbp_exists=False,
            goals_found=0,
            flow_attempted=False,
            failure_reason="no_pbp_data",
        )
        with caplog.at_level(logging.DEBUG, logger="app.services.pipeline.helpers.flow_debug_logger"):
            log.emit()
        nhl = [r for r in caplog.records if r.message == "flow_pipeline_nhl_debug"][0]
        assert nhl.failure_reason == "no_pbp_data"
        assert nhl.pbp_exists is False
        assert nhl.flow_attempted is False


class TestEmitOnce:
    """The single per-pipeline emission must not double-fire."""

    def test_emit_is_idempotent(self, caplog):
        log = FlowDebugLogger(game_id=1, league="NBA")
        with caplog.at_level(logging.INFO, logger="app.services.pipeline.helpers.flow_debug_logger"):
            log.emit()
            log.emit()
        info_records = [r for r in caplog.records if r.message == "flow_pipeline_debug"]
        assert len(info_records) == 1


class TestRegistry:
    """get_or_create / get / pop coordinate cross-stage access by run_id."""

    def test_get_or_create_returns_same_instance(self):
        a = get_or_create_logger(run_id=10, game_id=1, league="NBA")
        b = get_or_create_logger(run_id=10, game_id=1, league="NBA")
        assert a is b

    def test_get_returns_registered_logger(self):
        a = get_or_create_logger(run_id=11, game_id=1, league="NBA")
        assert get_logger(11) is a

    def test_get_returns_none_when_not_registered(self):
        assert get_logger(999) is None
        assert get_logger(None) is None

    def test_pop_removes_from_registry(self):
        get_or_create_logger(run_id=12, game_id=1, league="NBA")
        popped = pop_logger(12)
        assert popped is not None
        assert get_logger(12) is None

    def test_none_run_id_returns_ephemeral_unregistered_logger(self):
        log = get_or_create_logger(run_id=None, game_id=1, league="NBA")
        assert log.run_id is None
        # Not registered, so get_logger(None) is None
        assert get_logger(None) is None

    def test_league_backfilled_when_initially_unknown(self):
        first = get_or_create_logger(run_id=20, game_id=1, league=None)
        assert first.league is None
        second = get_or_create_logger(run_id=20, game_id=1, league="NHL")
        assert second is first
        assert first.league == "NHL"


class TestEmitsStructuredInfoLog:
    """Each pipeline run emits a single structured INFO entry with all fields."""

    def test_info_log_contains_all_per_game_fields(self, caplog):
        log = FlowDebugLogger(game_id=77, league="NBA", run_id=1)
        log.set_final_status("completed")
        log.record_data_metrics(
            source_play_count=300, scoring_event_count=80, lead_change_count=4
        )
        log.record_archetype("late_separation")
        log.record_boundary(moment_index=5, trigger="lead_change", priority=1)
        log.record_rejected_boundary(
            moment_index=33, reason="period_boundary_no_state_change"
        )
        log.record_prompt_payload("prompt")
        log.record_generation_result("PUBLISH")
        log.record_validation_result(status="passed", warnings=[], errors=[])
        log.record_persist_decision(persisted=True)

        with caplog.at_level(logging.INFO, logger="app.services.pipeline.helpers.flow_debug_logger"):
            log.emit()
        records = [r for r in caplog.records if r.message == "flow_pipeline_debug"]
        assert len(records) == 1
        rec = records[0]
        # Spot-check every field listed in the issue's per-game record
        assert rec.game_id == 77
        assert rec.league == "NBA"
        assert rec.final_status == "completed"
        assert rec.source_play_count == 300
        assert rec.scoring_event_count == 80
        assert rec.lead_change_count == 4
        assert rec.selected_archetype == "late_separation"
        assert rec.selected_boundaries[0]["trigger"] == "lead_change"
        assert rec.rejected_boundaries[0]["reason"] == "period_boundary_no_state_change"
        assert rec.prompt_payload_hash is not None
        assert rec.generation_result == "PUBLISH"
        assert rec.validation_status == "passed"
        assert rec.persisted is True
        assert rec.skip_reason is None
