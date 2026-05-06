"""Structured per-game debug logger for the narrative pipeline.

Accumulates a single structured record across pipeline stages so that, when a
generated flow looks wrong, it is obvious from one log line whether the
problem is in data, boundary selection, prompt, generation, or validation.

Per-game record (INFO):
    game_id, league, final_status,
    source_play_count, scoring_event_count, lead_change_count,
    selected_archetype, selected_boundaries (each with trigger reason),
    rejected_boundaries (each with reason),
    prompt_payload_hash, generation_result (PUBLISH/REGENERATE/FALLBACK),
    validation_status, validation_warnings, validation_errors,
    persisted, skip_reason

NHL-specific record (DEBUG):
    game_id, was_considered, pbp_exists, goals_found,
    flow_attempted, failure_reason

Debug payload save: when ``FLOW_DEBUG_SAVE=true`` env var is set,
``record_prompt_payload`` writes the full prompt JSON to
``debug/flow_{game_id}.json`` for post-hoc inspection.

The logger is keyed by ``run_id`` in a process-local registry. The executor
creates one at the start of a pipeline run and emits/pops it at the end.
Stages retrieve the active logger via ``get_logger(run_id)``; if no logger
is registered (e.g. unit tests calling a stage directly) the helpers no-op.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FLOW_DEBUG_SAVE_ENV = "FLOW_DEBUG_SAVE"
_FLOW_DEBUG_SAVE_DIR_ENV = "FLOW_DEBUG_SAVE_DIR"
_DEFAULT_DEBUG_DIR = "debug"


@dataclass
class BoundaryDecision:
    """One accepted boundary split point with the trigger that placed it."""

    moment_index: int
    trigger: str
    priority: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"moment_index": self.moment_index, "trigger": self.trigger}
        if self.priority is not None:
            result["priority"] = self.priority
        return result


@dataclass
class RejectedBoundary:
    """One candidate boundary that was rejected and why."""

    moment_index: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"moment_index": self.moment_index, "reason": self.reason}


@dataclass
class FlowDebugLogger:
    """Accumulates per-game pipeline debug fields and emits one structured log."""

    game_id: int
    league: str | None = None
    run_id: int | None = None

    # Data metrics
    source_play_count: int | None = None
    scoring_event_count: int | None = None
    lead_change_count: int | None = None

    # Boundary selection
    selected_archetype: str | None = None
    selected_boundaries: list[BoundaryDecision] = field(default_factory=list)
    rejected_boundaries: list[RejectedBoundary] = field(default_factory=list)

    # Prompt + generation
    prompt_payload_hash: str | None = None
    prompt_payload_path: str | None = None
    generation_result: str | None = None  # PUBLISH | REGENERATE | FALLBACK
    fallback_reason: str | None = None

    # Validation
    validation_status: str | None = None
    validation_warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)

    # Persistence
    persisted: bool | None = None
    skip_reason: str | None = None

    # Final pipeline status (set by executor at end)
    final_status: str | None = None

    # NHL-specific fields (always populated for NHL games)
    nhl_was_considered: bool | None = None
    nhl_pbp_exists: bool | None = None
    nhl_goals_found: int | None = None
    nhl_flow_attempted: bool | None = None
    nhl_failure_reason: str | None = None

    _emitted: bool = False

    # ------------------------------------------------------------------
    # Mutation API
    # ------------------------------------------------------------------

    def record_data_metrics(
        self,
        *,
        source_play_count: int | None = None,
        scoring_event_count: int | None = None,
        lead_change_count: int | None = None,
    ) -> None:
        if source_play_count is not None:
            self.source_play_count = source_play_count
        if scoring_event_count is not None:
            self.scoring_event_count = scoring_event_count
        if lead_change_count is not None:
            self.lead_change_count = lead_change_count

    def record_archetype(self, archetype: str | None) -> None:
        self.selected_archetype = archetype

    def record_boundary(self, moment_index: int, trigger: str, priority: int | None = None) -> None:
        self.selected_boundaries.append(
            BoundaryDecision(moment_index=moment_index, trigger=trigger, priority=priority)
        )

    def record_rejected_boundary(self, moment_index: int, reason: str) -> None:
        self.rejected_boundaries.append(
            RejectedBoundary(moment_index=moment_index, reason=reason)
        )

    def record_prompt_payload(self, payload: Any) -> str:
        """Compute SHA-256 of the prompt payload and optionally save it.

        ``payload`` may be a string or a JSON-serializable object. The hash is
        computed over the canonical JSON form for objects, or the raw bytes
        for strings — either way it's stable across runs of the same input.

        When ``FLOW_DEBUG_SAVE=true``, the full payload is written to
        ``debug/flow_{game_id}.json``. Returns the computed hash so callers
        can include it in their own logs if needed.
        """
        if isinstance(payload, str):
            serialized = payload
        else:
            serialized = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        self.prompt_payload_hash = digest

        if _flow_debug_save_enabled():
            # Narrow ``OSError`` catch: this debug-payload writer is
            # opt-in (FLOW_DEBUG_SAVE=true) and best-effort by design — a
            # filesystem failure must not break the pipeline. We catch only
            # OSError so a JSON-serialization bug (TypeError) or programming
            # error still propagates.
            try:
                save_dir = Path(os.environ.get(_FLOW_DEBUG_SAVE_DIR_ENV) or _DEFAULT_DEBUG_DIR)
                save_dir.mkdir(parents=True, exist_ok=True)
                path = save_dir / f"flow_{self.game_id}.json"
                envelope = {
                    "game_id": self.game_id,
                    "league": self.league,
                    "prompt_payload_hash": digest,
                    "payload": payload if not isinstance(payload, str) else None,
                    "payload_text": payload if isinstance(payload, str) else None,
                }
                path.write_text(json.dumps(envelope, default=str, indent=2))
                self.prompt_payload_path = str(path)
            except OSError:
                logger.warning(
                    "flow_debug_payload_save_failed",
                    extra={"game_id": self.game_id},
                    exc_info=True,
                )
        return digest

    def record_validation_result(
        self,
        *,
        status: str,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        self.validation_status = status
        if warnings is not None:
            self.validation_warnings = list(warnings)
        if errors is not None:
            self.validation_errors = list(errors)

    def record_generation_result(
        self, decision: str, fallback_reason: str | None = None
    ) -> None:
        """Record PUBLISH / REGENERATE / FALLBACK decision.

        ``fallback_reason`` is required when ``decision == "FALLBACK"`` so the
        log makes it explicit *why* the template path was used.
        """
        self.generation_result = decision
        if decision == "FALLBACK":
            self.fallback_reason = fallback_reason or "unspecified"

    def record_persist_decision(
        self, *, persisted: bool, skip_reason: str | None = None
    ) -> None:
        self.persisted = persisted
        if not persisted and skip_reason:
            self.skip_reason = skip_reason

    def record_nhl_state(
        self,
        *,
        was_considered: bool | None = None,
        pbp_exists: bool | None = None,
        goals_found: int | None = None,
        flow_attempted: bool | None = None,
        failure_reason: str | None = None,
    ) -> None:
        if was_considered is not None:
            self.nhl_was_considered = was_considered
        if pbp_exists is not None:
            self.nhl_pbp_exists = pbp_exists
        if goals_found is not None:
            self.nhl_goals_found = goals_found
        if flow_attempted is not None:
            self.nhl_flow_attempted = flow_attempted
        if failure_reason is not None:
            self.nhl_failure_reason = failure_reason

    def set_final_status(self, status: str) -> None:
        self.final_status = status

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    def to_payload(self) -> dict[str, Any]:
        """Serialize the accumulated record for structured logging."""
        return {
            "game_id": self.game_id,
            "league": self.league,
            "final_status": self.final_status,
            "source_play_count": self.source_play_count,
            "scoring_event_count": self.scoring_event_count,
            "lead_change_count": self.lead_change_count,
            "selected_archetype": self.selected_archetype,
            "selected_boundaries": [b.to_dict() for b in self.selected_boundaries],
            "rejected_boundaries": [r.to_dict() for r in self.rejected_boundaries],
            "prompt_payload_hash": self.prompt_payload_hash,
            "prompt_payload_path": self.prompt_payload_path,
            "generation_result": self.generation_result,
            "fallback_reason": self.fallback_reason,
            "validation_status": self.validation_status,
            "validation_warnings": list(self.validation_warnings),
            "validation_errors": list(self.validation_errors),
            "persisted": self.persisted,
            "skip_reason": self.skip_reason,
        }

    def emit(self) -> None:
        """Emit the accumulated record; safe to call twice (second call no-ops)."""
        if self._emitted:
            return
        self._emitted = True

        is_nhl = (self.league or "").upper() == "NHL"
        if is_nhl:
            self._infer_nhl_state()

        payload = self.to_payload()
        logger.info("flow_pipeline_debug", extra=payload)

        if is_nhl:
            nhl_payload = {
                "game_id": self.game_id,
                "was_considered": self.nhl_was_considered,
                "pbp_exists": self.nhl_pbp_exists,
                "goals_found": self.nhl_goals_found,
                "flow_attempted": self.nhl_flow_attempted,
                "failure_reason": self.nhl_failure_reason,
            }
            logger.debug("flow_pipeline_nhl_debug", extra=nhl_payload)

    def _infer_nhl_state(self) -> None:
        """Backfill any NHL fields the caller didn't set explicitly.

        For NHL games run through the pipeline, the data we already collect
        — source_play_count, scoring_event_count, persisted, final_status —
        lets us derive the NHL diagnostic fields without having to thread
        extra state through every stage.
        """
        if self.nhl_was_considered is None:
            self.nhl_was_considered = True
        if self.nhl_flow_attempted is None:
            # If we got far enough to record any data metrics, the pipeline
            # attempted to build a flow even if it failed downstream.
            self.nhl_flow_attempted = (
                self.source_play_count is not None or self.persisted is not None
            )
        if self.nhl_pbp_exists is None and self.source_play_count is not None:
            self.nhl_pbp_exists = self.source_play_count > 0
        if self.nhl_goals_found is None and self.scoring_event_count is not None:
            self.nhl_goals_found = self.scoring_event_count
        if self.nhl_failure_reason is None:
            if self.skip_reason:
                self.nhl_failure_reason = self.skip_reason
            elif self.final_status and self.final_status not in {"completed", "success"}:
                self.nhl_failure_reason = self.final_status


# ---------------------------------------------------------------------------
# Process-local registry
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_active_loggers: dict[int, FlowDebugLogger] = {}


def _flow_debug_save_enabled() -> bool:
    return os.environ.get(_FLOW_DEBUG_SAVE_ENV, "").lower() in {"1", "true", "yes"}


def get_or_create_logger(
    run_id: int | None, game_id: int, league: str | None = None
) -> FlowDebugLogger:
    """Return the active logger for ``run_id``, creating one if absent.

    When ``run_id`` is ``None`` (e.g. tests calling a stage directly without
    an executor), an ephemeral logger is returned that is NOT registered;
    callers can still record fields on it but it won't be retrieved by
    ``get_logger``. This keeps stages safe to call in isolation.
    """
    if run_id is None:
        return FlowDebugLogger(game_id=game_id, league=league)
    with _lock:
        existing = _active_loggers.get(run_id)
        if existing is not None:
            if existing.league is None and league is not None:
                existing.league = league
            return existing
        new_logger = FlowDebugLogger(game_id=game_id, league=league, run_id=run_id)
        _active_loggers[run_id] = new_logger
        return new_logger


def get_logger(run_id: int | None) -> FlowDebugLogger | None:
    """Return the active logger for ``run_id`` or ``None`` if not registered."""
    if run_id is None:
        return None
    with _lock:
        return _active_loggers.get(run_id)


def pop_logger(run_id: int | None) -> FlowDebugLogger | None:
    """Remove and return the logger for ``run_id``."""
    if run_id is None:
        return None
    with _lock:
        return _active_loggers.pop(run_id, None)


def reset_for_tests() -> None:
    """Clear the registry — for use in unit tests only."""
    with _lock:
        _active_loggers.clear()
