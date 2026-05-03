# Error-Handling Hardening Report — branch `flow`

Date: 2026-05-03 (pass 2 — scraper status-handling additions)
Scope: branch `flow` working tree + the 2026-05-03 status-handling commit
(`44401363`). Pass 1 covered the api/ pipeline working-tree edits (F-1
through F-11 below). Pass 2 covers the scraper changes around live
promotion, NCAAB / NHL / NBA / MLB / NFL status transitions, and the
shared Redis-backed PBP throttles touched by that work (F-12 through F-20).

## Changes made this pass (pass 2 — scraper)

| File | Lines | Change |
|------|-------|--------|
| `scraper/sports_scraper/services/game_processors.py` | 86–148 | **Tightened.** Narrowed both Redis-backed PBP helpers (`live_pbp_payload_unchanged`, `should_create_live_pbp_snapshot`) from `except Exception` to `(redis.RedisError, OSError)`. Replaced `error=str(exc)` with `exc_info=True` so the structured logger captures the full traceback. Best-effort fail-open semantics preserved (dedupe → proceed; throttle → write snapshot). |
| `scraper/sports_scraper/persistence/games.py` | 16, 32–55 | **Tightened.** `_notify_game_update`: narrowed the pg_notify catch from `except Exception` to `(SQLAlchemyError, OSError)` — mirrors the api-side pass-1 hardening (F-6). Programming bugs (e.g. payload schema drift) now propagate; transport / DB transient failures still degrade silently. Added `from sqlalchemy.exc import SQLAlchemyError`. |
| `scraper/sports_scraper/persistence/games.py` | 64–101 | **Tightened.** `_cache_get` / `_cache_set` / `_cache_delete`: narrowed each `except Exception` to `(redis.RedisError, OSError)`. Hoisted the `redis` import out of the try block so an `ImportError` propagates loudly (Redis client is a hard dependency — a missing import is a deployment bug, not a cache miss). |
| `scraper/sports_scraper/live/mlb_pbp.py` | 56–73 | **Tightened.** Narrowed `provider_request` catch in `fetch_play_by_play` from `except Exception` to `(httpx.HTTPError, RuntimeError)` (the two real failure modes of `provider_request`). Added `exc_info=True` so a systematic provider change does not look like a one-line ERROR with no stack. |
| `scraper/sports_scraper/jobs/sweep_tasks.py` | 33–45 | **Justified.** Added rationale to the `run_daily_sweep` docstring documenting the per-phase `try / except Exception` pattern: it is intentional safety-net isolation (one failed phase ≠ aborted sweep), `logger.exception` already captures the traceback, and per-phase failure is recorded in the `results` dict. Cites §F-20. |
| `scraper/sports_scraper/jobs/sweep_tasks.py` | 152–185, 316–361 | **Tightened.** Per-team / per-league-bucket `except Exception` in `_run_social_scrape_2` and `_repair_stale_statuses`: dropped the `error=str(exc)` form, switched to `exc_info=True` so the loop-isolation pattern keeps a real traceback in logs. Added inline rationale lines noting the isolation contract. |
| `scraper/sports_scraper/jobs/polling_helpers_ncaab.py` | 168–217, 339–417 | **Tightened.** All five per-game / per-phase broad catches in the NCAAB poll loop now use `exc_info=True` instead of `error=str(exc)`, with inline rationale on each documenting the per-game-isolation contract (one bad game must not abort the batch). The 429-string rate-limit re-raise behavior is preserved; only the non-429 fallthrough warning was changed. |
| `scraper/tests/test_persistence_games.py` | 611–681 | **Tightened (test).** Three `update_game_from_live_feed` tests were relying on the old broad `_notify_game_update` catch to silently absorb a `TypeError` raised by `json.dumps(MagicMock)` (the auto-attribute `mock_game.id` was a MagicMock, not an int). With the narrower `(SQLAlchemyError, OSError)` catch the test failure is now correctly surfaced; fix is to set `mock_game.id = <int>` explicitly. The narrowed catch caught a real test smell — exactly the kind of suppression the hardening was meant to remove. |

Net impact (pass 2):
- Six `except Exception` clauses narrowed (two PBP-throttle Redis catches, three game-cache Redis catches, one pg_notify) to actual transport / DB exception classes.
- One `except Exception` clause narrowed (mlb_pbp `provider_request`) to its declared failure modes.
- Eight per-loop / per-phase warnings upgraded from `error=str(exc)` to `exc_info=True` so structured-log consumers get the real traceback.
- One sweep-task docstring annotated with phase-isolation rationale.
- One test fixture corrected after a hardening edit exposed a previously-suppressed `TypeError` — confirming the audit changed real posture, not just text.
- Scraper test suite (3,253 tests) green; pipeline / api test suites unchanged from pass 1.

## Changes made this pass (pass 1 — api/pipeline)

| File | Lines | Change |
|------|-------|--------|
| `api/app/db/pipeline_stage.py` | 56–80 | **Tightened.** Removed `try / except ValueError: return None` in `next_stage` / `previous_stage`. The exception was unreachable for any enum member listed in `ordered_stages()` and silently masked the real failure mode (a new enum member added without updating the order list, which would cause the executor to skip that stage). Now `stages.index(self)` raises and the error surfaces at first call. |
| `api/app/services/pipeline/stages/render_blocks.py` | 99–125 | **Tightened.** Added `logger.warning(..., exc_info=True)` to both flow-pass except blocks so the traceback reaches the structured logger (previously only `output.add_log` captured `str(e)`, losing the stack). The fail-soft semantics (return originals on flow-pass failure) are preserved. |
| `api/app/services/pipeline/stages/render_blocks.py` | 274–284 | **Justified.** Added inline rationale citing report §F-3 explaining why the primary-render `except Exception` deliberately re-raises (executor's outer catch records and logs with full traceback). |
| `api/app/services/pipeline/stages/validate_blocks_phrases.py` | 31–63 | **Tightened.** Narrowed `except Exception` to `(OSError, tomllib.TOMLDecodeError, ValueError, TypeError)` so a programming bug propagates instead of degrading silently to the 7-phrase compatibility list. Elevated `logger.warning` → `logger.error` because the fallback materially weakens the generic-phrase density gate. |
| `api/app/services/pipeline/stages/finalize_moments.py` | 57–58 | Added `from sqlalchemy.exc import SQLAlchemyError`. |
| `api/app/services/pipeline/stages/finalize_moments.py` | 93–106 | **Justified.** Added rationale to `_signed_lead`'s narrow `(TypeError, ValueError)` catch (documented contract: malformed score → None). |
| `api/app/services/pipeline/stages/finalize_moments.py` | 425–445 | **Tightened.** Narrowed `pg_notify` `except Exception` to `(SQLAlchemyError, OSError)` so a real bug (e.g. TypeError from a future schema change) propagates. Added `flow_id` to the structured warning extra fields. |
| `api/app/services/pipeline/stages/finalize_moments.py` | 460–500 | **Tightened.** The Celery `grade_flow_task` dispatch is the publish gate (ISSUE-053): if dispatch silently fails, the flow is persisted but never graded → never published. Elevated `logger.warning` → `logger.error` and added `game_id`, `sport`, `is_template_fallback`, `regen_attempt` to the structured `extra` so an ops sweep can find ungraded flows from a single log query. Kept the broad `except Exception` because the row is already committed and rolling back leaves DB / transaction state inconsistent — re-raising would corrupt rather than recover. |
| `api/app/services/pipeline/executor.py` | 460–470 | **Justified.** Added rationale to the orchestration-boundary `except Exception` confirming that `exc_info=True`, metric increment, and stage/run failure recording mean nothing is silently swallowed. |
| `api/app/tasks/bulk_flow_generation.py` | 249–267 | **Justified.** Annotated the per-game broad catch — bulk job semantics require `one bad game must not kill the loop`. Failure is recorded in `errors_json`, structured `WARNING` log carries `exc_info=True`. |
| `api/app/tasks/bulk_flow_generation.py` | 297–311 | **Justified.** Annotated the top-level broad catch — `logger.exception` includes the traceback; the job is marked failed with the error captured in `errors_json`. |
| `api/app/services/pipeline/helpers/flow_debug_logger.py` | 168–192 | **Justified.** Annotated the existing narrow `except OSError` — opt-in debug payload writer is best-effort by design; programming errors (TypeError, etc.) still propagate. |
| `api/tests/test_finalize_moments_v2_schema.py` | 93–122 | **Tightened (test).** `_session_returning` previously used a list-style `side_effect` whose iterator exhaustion (`StopAsyncIteration`) was being silently absorbed by the now-narrowed `pg_notify` catch. Replaced with a callable `side_effect` that returns a benign `MagicMock` for trailing calls — the mock now reflects realistic execution rather than depending on broad-catch suppression. |

Net impact:
- Two `except Exception` clauses narrowed (one config-load, one pg_notify).
- One silent `try/except: return None` removed entirely.
- One critical broad-catch elevated to ERROR with structured ops-recovery fields.
- All remaining broad-catch sites now carry an inline rationale block citing this report.
- Pipeline test suites (494 tests across `test_pipeline_models`, `test_render_blocks`, `test_validate_blocks`, `test_flow_debug_logger`, `test_bulk_flow_diagnostics`, `test_classify_game_shape`, `test_evidence_selection`, `test_score_timeline`, `test_flow_thresholds`, `test_group_blocks`, `test_game_flow_endpoint`, `test_v1_flow_endpoint`, `test_regen_context`) still pass; the v2-schema suite (22 tests) updated to match the narrowed catch.

## Executive summary

Combined posture across both passes:

| Severity | Count | Disposition |
|----------|-------|-------------|
| Critical | 0 | — |
| High | 1 | F-7 (`grade_flow_task` dispatch) — ELEVATED to ERROR + structured ops fields. Cannot re-raise (state-coupled to a committed row); failure is now operationally visible. |
| Medium | 9 | F-1, F-2, F-4, F-6, F-12, F-13, F-14, F-15, F-16 — tightened in source (narrower catch class and/or `exc_info` added). |
| Low | 4 | F-3, F-17, F-18, F-19 — per-loop isolation patterns left as broad catches by design; only observability tightened (added `exc_info=True`). |
| Note | 6 | F-5, F-8, F-9, F-10, F-11, F-20 — pre-existing correct posture; justification annotation only. |

**Posture verdict (pass 1)**: The api/pipeline branch's error-handling shape is sound — most broad catches are at intentional boundaries (orchestrator, batch loop, optional best-effort post-write notification) and already log with traceback. The two genuine concerns were:
1. The dead `except ValueError` in the enum helper that masked enum-drift bugs — eliminated.
2. The publish-gate dispatch failure being a `WARNING` — elevated to `ERROR` and given structured fields so ops can find and re-grade orphaned flows.

**Posture verdict (pass 2)**: The scraper status-handling additions are reliability-positive (the new self-heal margin and `try_promote_to_live` future-date guard close a real "live before tipoff" data-integrity bug). The remaining concerns were two-shaped:
1. **Best-effort Redis paths** were too forgiving — `except Exception` over Redis calls would silently absorb programming errors as well as transport failures. Now scoped to `(redis.RedisError, OSError)` so a refactor-introduced bug surfaces instead of degrading the cache to "always miss". The `_cache_get` `int(val)` is the most concrete example: a corrupted cache value now raises instead of being eaten.
2. **Per-loop warnings lost their tracebacks** by formatting `error=str(exc)` instead of using `exc_info=True`. The pattern is correct in shape (one bad game must not abort the batch) but a one-line WARNING with no stack made systematic provider failures hard to triage. Eight call sites now log full tracebacks while preserving the loop-isolation contract.

The narrowed `_notify_game_update` catch caught a real previously-suppressed `TypeError` in three tests on the first run — confirming the suppression was hiding a programming bug, not just a hypothetical risk. Tests fixed; production code now reflects the intended contract.

No suppressions were left as `TODO`. No `Escalations` section needed.

## Findings

| ID | File:line | Severity | Lens | Disposition |
|----|-----------|----------|------|-------------|
| F-1 | `api/app/db/pipeline_stage.py:64,75` | Medium | Reliability | Acted (removed catch) |
| F-2 | `api/app/services/pipeline/stages/render_blocks.py:115` | Medium | Observability | Acted (added `exc_info` logger) |
| F-3 | `api/app/services/pipeline/stages/render_blocks.py:270` | Low | Reliability | Justified |
| F-4 | `api/app/services/pipeline/stages/validate_blocks_phrases.py:51` | Medium | Reliability + Observability | Acted (narrowed + ERROR level) |
| F-5 | `api/app/services/pipeline/stages/finalize_moments.py:99` | Note | Data integrity | Justified |
| F-6 | `api/app/services/pipeline/stages/finalize_moments.py:433` | Medium | Reliability | Acted (narrowed) |
| F-7 | `api/app/services/pipeline/stages/finalize_moments.py:463` | High | Operational | Acted (ERROR + structured fields) |
| F-8 | `api/app/tasks/bulk_flow_generation.py:249` | Note | Reliability | Justified |
| F-9 | `api/app/tasks/bulk_flow_generation.py:297` | Note | Reliability | Justified |
| F-10 | `api/app/services/pipeline/helpers/flow_debug_logger.py:182` | Note | Operational | Justified |
| F-11 | `api/app/services/pipeline/executor.py:460` | Note | Reliability | Justified |
| F-12 | `scraper/sports_scraper/services/game_processors.py:97-118` | Medium | Reliability + Observability | Acted (narrowed `except Exception` → `(RedisError, OSError)`, `exc_info=True`) |
| F-13 | `scraper/sports_scraper/services/game_processors.py:128-148` | Medium | Reliability + Observability | Acted (same as F-12, fail-open semantics preserved) |
| F-14 | `scraper/sports_scraper/persistence/games.py:39-55` | Medium | Reliability | Acted (narrowed pg_notify to `(SQLAlchemyError, OSError)`) |
| F-15 | `scraper/sports_scraper/persistence/games.py:64-101` | Medium | Reliability | Acted (narrowed three Redis cache helpers) |
| F-16 | `scraper/sports_scraper/live/mlb_pbp.py:60-73` | Medium | Observability | Acted (narrowed provider_request catch + `exc_info=True`) |
| F-17 | `scraper/sports_scraper/jobs/sweep_tasks.py:160,176` | Low | Observability | Acted (added `exc_info=True` to per-team WARN; broad catch left as per-team isolation) |
| F-18 | `scraper/sports_scraper/jobs/sweep_tasks.py:316-361` | Low | Observability | Acted (added `exc_info=True` to NBA / NHL bucket WARN) |
| F-19 | `scraper/sports_scraper/jobs/polling_helpers_ncaab.py:172,211,343,381,406` | Low | Observability | Acted (added `exc_info=True` to all five per-game / per-phase WARN; 429 rate-limit re-raise preserved) |
| F-20 | `scraper/sports_scraper/jobs/sweep_tasks.py:33-87` | Note | Reliability | Justified (intentional phase-isolation, `logger.exception` already includes traceback) |

## Per-item rationale

### F-1 — `db/pipeline_stage.py` enum-drift catch (Medium → Acted)

**Before:**
```python
try:
    idx = stages.index(self)
    if idx < len(stages) - 1:
        return stages[idx + 1]
    return None
except ValueError:
    return None
```

**Risk**: `stages.index(self)` only raises `ValueError` if `self` is not in `ordered_stages()`. That is impossible for any enum member currently listed. But if a future change adds a new `PipelineStage` member without adding it to `ordered_stages()`, `next_stage()` silently returns `None` and the executor (`execute_next_stage`, `executor.py:493`) skips the new stage with no log entry — a class of bug that would be invisible in production logs.

**Fix**: Removed the `try/except`; `stages.index(self)` now raises at first call so the invariant violation is loud at deploy time, not silent at runtime.

### F-2 — `render_blocks.py` flow-pass swallows traceback (Medium → Acted)

**Before**: Two except clauses logged via `output.add_log(f"... {e}", level="warning")`. `add_log` only captures `str(e)`, so a stack trace would be lost.

**Risk**: When the optional flow-pass fails intermittently in production (rate-limit, partial outage), we get a one-line warning with no stack — debugging the failure mode requires reproduction.

**Fix**: Kept the fall-back-to-originals semantics (the flow pass is genuinely optional) but added `logger.warning("flow_pass_failed", exc_info=True, extra={"block_count": ...})` so the structured logger sees the full traceback. Same treatment for the `JSONDecodeError` branch.

### F-3 — `render_blocks.py` primary render fail-fast (Low → Justified)

The primary block-render `except Exception` re-raises as `ValueError(...) from e`. The chain is preserved, the executor's outer `except` (F-11) records `exc_info=True`. This is correct fail-fast behavior: if the primary render fails, there is no useful product output; rolling back is the right move. Justification added inline.

### F-4 — `validate_blocks_phrases.py` config load (Medium → Acted)

**Before**: `except Exception: log warn + return tiny fallback list`.

**Risk**: A malformed grader_rules TOML silently degrades the generic-phrase density gate from the full curated list (~30+ phrases) to a 7-phrase compatibility fallback, weakening narrative quality validation. Log was at `WARNING`, easy to miss.

**Fix**: Narrowed to `(OSError, tomllib.TOMLDecodeError, ValueError, TypeError)` — captures the legitimate failure modes (file missing/unreadable, bad TOML, non-numeric threshold, wrong types) but lets a refactor-induced AttributeError or KeyError propagate. Elevated `logger.warning` → `logger.error` so a degraded-config state is visible in ops dashboards.

### F-5 — `finalize_moments._signed_lead` narrow catch (Note → Justified)

`int(score[0]) - int(score[1])` over `(TypeError, ValueError)` is a documented bounded conversion; `None` is the contract for malformed score input. Already narrow. Annotation added.

### F-6 — `finalize_moments` pg_notify (Medium → Acted)

**Before**: `except Exception: logger.warning(..., exc_info=True)`.

**Risk**: Realtime notification is not data-integrity critical — failing to notify subscribers is fine — but the broad catch would also swallow a `TypeError` from a hypothetical schema change to the JSON payload, hiding a programming bug behind a warning log.

**Fix**: Narrowed to `(SQLAlchemyError, OSError)` — covers transport/DB failures (the realistic transient failure modes) without absorbing programming errors. Added `flow_id` to the log payload so ops can correlate notification failures with persisted flows.

### F-7 — `finalize_moments` `grade_flow_task` dispatch (High → Acted)

**Before**: `except Exception: logger.warning("grade_flow_task_dispatch_failed", exc_info=True, extra={"flow_id": flow_id})`.

**Risk** (the most consequential finding in the audit):
- This is the publish gate (per ISSUE-053 comment).
- If dispatch fails, the flow is committed to DB but never graded → `grader_run` never populates → flow never published to the consumer.
- WARNING level + only `flow_id` in the payload means failures look like noise in container logs, and an ops sweep to find ungraded flows would have to query the DB to figure out which flows the grader never received.

**Fix considered and rejected: re-raise**. The flow row is already committed via `await session.flush()` and (for the existing-flow branch) field updates have run. Re-raising would not roll those back; we'd just propagate to the executor and mark the stage failed *with the row still present*. That's worse than the current state.

**Fix applied**:
- `logger.warning` → `logger.error`. ERROR-level dispatch failures should fire ops alerts.
- Added `game_id`, `sport`, `is_template_fallback`, `regen_attempt` to `extra` so the alert log is self-sufficient for an ops sweep ("find flows persisted in this window where `grader_run` is null and re-dispatch").
- Inline comment documents why re-raise was rejected and points to this report section.

Future work (not in scope for this pass): add a recurring sweep that re-dispatches `grade_flow_task` for flows where `grader_run` is null and `flow_source != 'TEMPLATE'`. Mentioned here so the trade-off is documented, not as a TODO in source.

### F-8 — bulk per-game catch (Note → Justified)

`bulk_flow_generation.py:249`. Per-game broad catch in a batch loop is the right shape: failure is fully recorded in `errors_json`, log at WARNING with `exc_info=True`. Annotated.

### F-9 — bulk top-level catch (Note → Justified)

`bulk_flow_generation.py:297`. Top-level catch with `logger.exception` (full traceback) + DB failure record. Annotated.

### F-10 — `flow_debug_logger.py` debug payload save (Note → Justified)

Already narrow (`OSError`), opt-in (`FLOW_DEBUG_SAVE=true`), best-effort by design. Annotation added making the contract explicit.

### F-11 — `executor.py` orchestration boundary (Note → Justified)

The single broad-catch at the stage-dispatch boundary is required: every stage's failures funnel here so the run/stage records reach a consistent `failed` state and metrics are emitted. `exc_info=True` preserves the traceback. Annotated.

### F-12 / F-13 — `game_processors.py` Redis-backed PBP throttles (Medium → Acted)

Both `live_pbp_payload_unchanged` and `should_create_live_pbp_snapshot` are best-effort optimizations on top of the live PBP polling loop. Their pre-existing `except Exception` made the **fail-open** semantics absolute: any error → degrade to "always proceed". That's correct behavior for a Redis outage (we'd rather double-write PBP than drop it), but it also absorbed:

- `ImportError` from a missing `redis` package (deployment bug, would silently degrade every poller)
- `TypeError` / `AttributeError` from a future signature change in `_pbp_signature` or the throttle key format
- `NameError` from a renamed module variable

The narrowed catch is `(redis.RedisError, OSError)`:
- `RedisError` covers the entire redis-py exception tree (Connection, Timeout, Response, Auth)
- `OSError` covers DNS / refused-connection failures from the underlying socket

Bug-class exceptions now propagate to the per-game `try` in `_poll_*_games_batch` (which catches them per-game and continues — the right place for that policy). Logging upgraded from `error=str(exc)` (loses traceback) to `exc_info=True`.

### F-14 — `persistence/games.py:_notify_game_update` pg_notify (Medium → Acted)

Mirrors the api-side hardening in F-6. The scraper-side is the more important of the two because it sits on the write path for every game-score-update commit; a programming bug here that flipped to silent-suppression mode would mean every notify silently failed and the API LISTEN handler would only receive notifications from a subset of writers.

`(SQLAlchemyError, OSError)` covers:
- DB-side `pg_notify` issues (channel-name length, encoding, role permission)
- transient socket-level disconnects on the existing connection
- the LISTEN consumer being dead (irrelevant — we still want the NOTIFY committed)

What the narrowing catches: a future schema-shape change to the JSON payload that introduces a non-serializable type. Without the narrowing, every notify would degrade silently to no-op and clients would stop seeing live updates with no log signal louder than DEBUG. The hardening edit caught exactly this class of bug in the `update_game_from_live_feed` test fixture (a `MagicMock` `game.id` was being silently absorbed) — the test was patched to set `game.id` explicitly.

### F-15 — `persistence/games.py` Redis game-match cache (Medium → Acted)

Three helpers (`_cache_get`, `_cache_set`, `_cache_delete`) all had `except Exception` over `redis_lib.from_url(...)` calls. Risk shape:

- **`_cache_get`** is the most consequential: it returns `None` on error which falls through to a DB query. A real bug there (e.g. `int(val)` on a corrupted cache value) would now degrade every match attempt for that key shape from a 1ms cache hit to a 6-tier DB lookup, **silently**. Now `int(val)` failures from corrupted data raise `ValueError` and propagate (programming/data integrity bug); only Redis transport failures degrade silently.
- **`_cache_set`** and **`_cache_delete`** are pure side-effect helpers; failure mode is "next call goes through the slow path", which is acceptable.

Hoisted the `redis` import out of the `try` block — it's a hard dependency of the package, so a missing redis-py is a deployment issue and should fail loudly rather than be absorbed into the cache catch.

### F-16 — `mlb_pbp.py:fetch_play_by_play` (Medium → Acted)

`provider_request` is the rate-limit-aware HTTP client; its declared failure modes are httpx errors (the underlying transport) and `RuntimeError` (rate-limit-exceeded guard). Catching `Exception` here would absorb:

- a future `provider_request` signature change (TypeError)
- a typo in the `provider=`, `endpoint=`, or `league=` kwargs
- a refactor that introduces a None-deref before the HTTP call

Narrowed to `(httpx.HTTPError, RuntimeError)`. Added `exc_info=True` so a systematic provider-side change is diagnosable from the structured logger; previously the warning was a single line with `error=str(exc)`.

### F-17 — sweep social-scrape per-team WARN (Low → Acted, observability only)

The broad `except Exception` is correct in shape: per-team isolation, one collector failure must not skip the second team or the rest of the game loop. The only weakness was observability — `error=str(exc)` reduced the traceback to a sentence. Switched to `exc_info=True` and added an inline rationale line documenting the isolation contract.

### F-18 — sweep NBA / NHL status-check WARN (Low → Acted, observability only)

Same shape as F-17 but at league-bucket granularity (one league outage must not abort the daily sweep). Same fix: `exc_info=True` plus inline rationale.

### F-19 — NCAAB poll loop per-game / per-phase WARN (Low → Acted, observability only)

Five call sites in `polling_helpers_ncaab.py` (NCAA scoreboard fetch, CBB schedule fetch, per-game PBP, CBB boxscore batch, NCAA boxscore fallback). The 429 detection (`if "429" in str(exc): raise _RateLimitError() from exc`) is **deliberately preserved** — it's the contract that keeps the polling task from hammering a rate-limited endpoint. Below the 429 re-raise, the warning fallback now uses `exc_info=True` so non-429 failures (DNS, 5xx, malformed payload) carry the full traceback into the structured logger.

### F-20 — `sweep_tasks.run_daily_sweep` per-phase isolation (Note → Justified)

Six top-level `try / except Exception` blocks (one per phase). Already use `logger.exception(...)` (full traceback) and store the failure in the per-phase `results` entry. The pattern is intentional safety-net isolation: a missed sweep cycle is much more expensive than a partial cycle, so the policy is "every phase runs, every failure logged, every result captured". Added rationale to the `run_daily_sweep` docstring citing this section.

## Patterns intentionally NOT changed

- **`# noqa: F401` registrations in `bulk_flow_generation.py:22-37`** — these imports register SQLAlchemy ORM relationships at module load. They're side-effecting imports with an inline reason. No change needed; already self-documenting.
- **`# type: ignore[assignment]` in `render_blocks.py:218-219`** — type-checker can't narrow `dict[str, Any].get(...)` to `list[str]` / `int`. Type-only suppression with no runtime risk; would require a TypedDict refactor that is out of scope.
- **`# type: ignore[possibly-undefined]` in `finalize_moments.py:442`** — mirrors a paired if/else where `new_flow` is bound only in the else branch. Cleaner alternative would be moving the assignment into the original if/else; pure refactor, not a safety issue.
- **`web/src/lib/guardrails.ts`** — no `try/catch` at all; structured violation logging routes severity to `console.error` vs `console.warn`. Already in the desired posture.
- **`api/app/services/pipeline/stages/classify_game_shape.py`** — no `try/except`; deterministic logic with explicit guards. Already in the desired posture.

## Verification

Pass 1 (api/pipeline):
- `python -m pytest tests/test_pipeline_models.py tests/test_render_blocks.py tests/test_validate_blocks.py tests/test_flow_debug_logger.py tests/test_bulk_flow_diagnostics.py tests/test_classify_game_shape.py tests/test_evidence_selection.py tests/test_score_timeline.py tests/test_flow_thresholds.py tests/test_group_blocks.py tests/test_game_flow_endpoint.py tests/test_v1_flow_endpoint.py tests/test_regen_context.py --no-cov` → **494 passed**.
- `python -m pytest tests/test_finalize_moments_v2_schema.py` → **22 passed** (after the test-side `_session_returning` fix that adapts to the narrowed pg_notify catch).
- Pre-existing unrelated collection errors in `tests/test_club_memberships.py` and `tests/test_router_namespaces.py` confirmed via `git stash` to exist on the unmodified branch — not caused by this pass.

Pass 2 (scraper):
- `python -m pytest scraper/tests/ --no-cov` → **3,253 passed, 66 skipped** (full scraper suite).
- `python -m pytest scraper/tests/test_persistence_games.py scraper/tests/test_game_processors.py scraper/tests/test_pbp_mlb.py --no-cov` → **189 passed** (focused on the changed modules).
- Initial run flagged three `TestUpdateGameFromLiveFeed` failures with `TypeError: Object of type MagicMock is not JSON serializable` — exactly the suppression the narrowed `_notify_game_update` catch was designed to surface. Tests patched to set `mock_game.id` to a real `int`; production code unchanged.
