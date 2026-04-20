# Abend Handling Audit

> Generated: 2026-04-18. Branch: aidlc_1.
> Scope: all Python (`api/`, `scraper/`) and TypeScript (`web/`, `packages/`) source files.
> Prior audit in `docs/AUDIT_REPORT.md` (2026-04-08) focused on Critical/High; this audit is exhaustive.

---

## Executive Summary

| Severity | Count | Status |
|----------|-------|--------|
| High | 3 | Fixed in-place |
| Medium | 9 | Documented; acceptable temporarily |
| Low | 11 | Noted; intentional or trivially benign |
| Note | 18 | Correct / well-designed patterns |

**Overall verdict:** No new Critical findings. Three High findings (silent failures with observability impact) fixed in-place. Remaining Medium items are best-effort degradations with clear risk bounds. The positive patterns — circuit breakers, Celery autoretry, the OpenAI retry loop — remain intact.

---

## Statistics

| Metric | Count |
|--------|-------|
| `except Exception` blocks | ~188 across 130+ files |
| `except (SpecificError):` blocks | ~45 |
| Bare `except:` blocks | 0 |
| Silent `pass` (no logging, production code) | 3 → **0 after fixes** |
| `return None/[]/{}` in except | ~55 |
| `logger.warning` in except (severity downgrade) | ~35 |
| `logger.debug` in except (significant downgrade) | ~6 |
| Celery `autoretry_for` tasks | ~20 |
| Manual retry loops | 2 |
| Circuit breaker patterns | 3 |
| `return_exceptions=True` gather | 1 |
| TypeScript `.catch(() => {})` empty | 1 → **0 after fix** |
| TypeScript `console.error` without re-throw | ~5 |

---

## Fixed Findings (High)

### H1 — `scraper/scripts/audit_data.py:255,259` — Silent DB Delete Failures

**Before:**
```python
try:
    session.execute(delete(db_models.SportsGameFlow).where(...))
except Exception:
    pass
try:
    session.execute(delete(db_models.SportsGameTimelineArtifact).where(...))
except Exception:
    pass
```

**After:** Added `logger.warning(..., exc_info=True)` to both blocks.

**Risk:** If these deletes failed silently, the following `session.execute(delete(SportsGame)...)` would violate FK constraints and crash with a cryptic error — the root cause (the flow/artifact delete failure) would be invisible.

**Classification:** High — data integrity + observability.

---

### H2 — `api/app/analytics/api/_model_routes.py:125,201` — Silent File Registry Lookup

**Before:**
```python
try:
    file_models = _model_registry.list_models(sport=sport, model_type=model_type)
    active_ids = {m["model_id"] for m in file_models if m.get("active")}
except Exception:
    pass
```
(appears at two call sites)

**After:** Added `logger.debug("model_registry_lookup_failed", exc_info=True)` to both.

**Risk:** If the file registry raises (corrupt metadata, permissions), all models report `active=False`. Admin UI silently shows wrong state with no hint of what failed.

**Classification:** High — observability (admin workflows affected).

---

### H3 — `web/src/app/admin/analytics/experiments/page.tsx:150` — Silent Promise.all Failure

**Before:**
```typescript
Promise.all([
  getAvailableFeatures(sportCode),
  listFeatureLoadouts(sportCode).catch(() => ({ loadouts: [] })),
])
  .then(([featRes, loadoutRes]) => { ... })
  .catch(() => {})   // ← silently swallows feature-load failure
  .finally(() => setFeaturesLoading(false));
```

**After:** `.catch((err) => { console.error("experiments_feature_load_failed", err); })`

**Risk:** If `getAvailableFeatures` fails, the user sees a perpetual loading state or empty grid with no error message and no console trace.

**Classification:** High — observability (admin UI becomes unusable silently).

---

## Medium Findings (Acceptable Temporarily)

### M1 — `api/app/analytics/services/model_service.py:210` — Silent JSON Corruption

```python
except (json.JSONDecodeError, OSError):
    pass
return None
```

**Context:** `_load_training_metadata(path)` — loads optional sidecar JSON from disk. Returns `None` on failure; callers check for `None`.

**Risk:** If a metadata file is corrupt, it silently returns `None`. The admin UI shows missing metrics with no indication of the cause. Should be at least `logger.warning`.

**Recommendation:** Upgrade to `logger.warning("training_metadata_load_failed", path=path, exc_info=True)`.

---

### M2 — `scraper/sports_scraper/golf/client.py:66` — Silent Settings Load

```python
try:
    from ..config import settings
    self._api_key = getattr(settings, "datagolf_api_key", "") or ""
except Exception:
    pass
```

**Context:** Lazy-loads API key at `DataGolfClient.__init__`. If settings import fails, key stays empty and the next API call fails with an auth error.

**Risk:** The auth failure is visible, but the root cause (settings misconfiguration) is invisible. Diagnostics are slow.

**Recommendation:** `logger.warning("datagolf_settings_load_failed", exc_info=True)`.

---

### M3 — `scraper/sports_scraper/services/pbp_nba.py:151` — Silent NBA PBP Parse Error

```python
except Exception:
    consecutive_misses += 1
    if consecutive_misses > 50:
        break
    continue
```

**Context:** Historical game-ID probe; iterates a large result set. Parse failures increment a counter; loop aborts at 50.

**Risk:** Corrupt or unexpected payloads silently inflate the miss counter. If `consecutive_misses` hits 50 on legitimate parse failures (not missing data), the probe aborts early and the scraper returns an incomplete lookup table — causing silently missed PBP ingestion.

**Recommendation:** `logger.debug("nba_game_id_probe_parse_error", exc_info=True)` on each miss; `logger.warning` when the loop aborts early due to misses.

---

### M4 — `api/app/routers/fairbet/live.py` — Rate Limiter Fails Open on Redis Error

*(Inherited from prior audit as M2 — unchanged.)*

**Context:** Redis failure means rate limiting is skipped, not enforced. Warning is logged.

**Risk:** Low — only affects rate limiting, not data correctness.

---

### M5 — `api/app/realtime/poller.py` — No Max-Failure Circuit Breaker

*(Inherited from prior audit as M3 — unchanged.)*

**Context:** Poller uses exponential backoff up to 300s but no hard stop after N consecutive failures.

**Risk:** Medium — can mask a dead DB connection indefinitely.

**Recommendation:** Add a failure count ceiling (e.g. 20 consecutive) that raises an alarm or restarts the poller.

---

### M6 — `api/app/analytics/services/mlb_roster_service.py` — `logger.debug` for Missing Lineup/Starter

*(Inherited from prior audit as M4.)*

**Context:** Three `return None` paths with `logger.debug` (not `warning`). Projected lineups are best-effort, so `debug` is intentional.

**Risk:** Low — `exc_info=True` is present; severity matches the feature's optional nature.

---

### M7 — `scraper/sports_scraper/persistence/games.py` — Silent Date Parse

*(Inherited from prior audit as M5.)*

**Context:** Several date fields silently become `None` on parse error. Fields stay nullable; downstream code handles None.

**Risk:** Low — affects display only, not game status transitions.

---

### M8 — `scraper/sports_scraper/jobs/live_odds_tasks.py` — 3 Silent Passes in Odds Tasks

*(Inherited from prior audit as M6.)*

**Context:** Best-effort cleanup in finally blocks; main result is already persisted.

**Risk:** Low.

---

### M9 — `api/app/analytics/services/simulation_engine.py` — Model Load Logged as Warning

*(Inherited from prior audit as M8.)*

**Context:** Simulation degrades to heuristic when model is unavailable. Warning is logged.

**Risk:** Low.

---

## Low Findings (Intentional or Trivially Benign)

### L1 — `api/app/realtime/ws.py:128` — `(TimeoutError, CancelledError): pass` on Ping Cancel

Correct shutdown pattern. Ping task is cancelled when websocket closes; absorbing the cancellation is correct.

### L2 — `api/app/realtime/sse.py:80` — `CancelledError: pass` on SSE Close

Client disconnect triggers task cancellation. Correct.

### L3 — `api/app/dependencies/roles.py:158` — `ValueError: pass` on URL Parse

Skips invalid Origin headers in CORS origin set. Benign; malformed origins just aren't added.

### L4 — `scraper/sports_scraper/utils/math.py:68` — `(ValueError, IndexError): pass` on Time Parse

Returns `None`; all callers handle `None`. A named-return pattern would be cleaner but this isn't risky.

### L5 — `scraper/sports_scraper/utils/provider_request.py:256` — `ValueError: pass` on Int Parse

Returns `None`; callers handle it. Same as L4.

### L6 — `api/app/tasks/_training_helpers.py:205` — `ImportError: pass` for LightGBM

Standard optional-dependency pattern. LightGBM is not installed in all environments.

### L7 — `api/app/routers/sports/common.py:188` — `(ValueError, TypeError): pass` on Stat Int Conversion

Inner function returns `None`; outer returns `None`. Stat fields are optional.

### L8 — `scraper/sports_scraper/services/phases/boxscore_phase.py:236` — Silent `record_ingest_error` Failure

The actual error was already logged at `logger.error` two lines above. This `pass` is in the nested cleanup `record_ingest_error` call — acceptable as a best-effort instrumentation write.

### L9 — `api/app/analytics/api/_model_routes.py` — File Registry as Optional Enrichment

After the H2 fix (debug log added), the pattern is acceptable. `active_ids` defaults to empty set; models show `active=False` which is safe.

### L10 — `infra/log-relay/server.py:152` — `KeyboardInterrupt: pass`

Correct server shutdown idiom.

### L11 — `api/app/analytics/services/model_service.py:210` — `(JSONDecodeError, OSError): pass`

Catalogued as M1 above. The function returns `None` safely; callers check. Upgraded to M1 pending a warning log addition.

---

## Note — Well-Designed Patterns (Keep)

### N1 — OpenAI 3-Retry Loop (`api/app/services/openai_client.py`)

Manual retry with attempt tracking, progressive sleep, `exc_info=True` logging, and a final re-raise. Best error handling in the codebase.

### N2 — Celery `autoretry_for` with Exponential Backoff

Golf, flow, and forecast tasks use `autoretry_for=(Exception,)` with `retry_backoff=True`. Provides automatic retry with Celery's built-in state tracking (failures are visible in admin).

### N3 — `asyncio.gather(*tasks, return_exceptions=True)` in Poller Shutdown

Correct pattern for cancelling a set of tasks without raising. The results are discarded intentionally.

### N4 — DB Session Rollback-then-Raise

`get_session()` context managers in both API and scraper roll back then re-raise. Textbook correct.

### N5 — Redis Lock Fail-Closed (`scraper/sports_scraper/celery_app.py`)

On Redis failure, the hold check returns `True` (task is held). Prevents duplicate dispatch under infrastructure instability.

### N6 — Realtime Poller Exponential Backoff (`api/app/realtime/poller.py`)

`_MAX_CONSECUTIVE_FAILURES=10`, `_MAX_BACKOFF_SECONDS=300`. Clean progressive backoff with warning logs at each failure.

### N7 — `run_manager.py` Fail-Closed on Task Existence Check

```python
except Exception as exc:
    logger.warning("social_task_exists_check_failed", error=str(exc))
    return True  # Fail-closed: assume task exists to prevent duplicate dispatch
```

Correct: fails closed with explanation comment.

### N8 — Live Scraper Error Pattern

All live scrapers (`mlb.py`, `nfl.py`, `nhl.py`, etc.) use `logger.error` + `return None/[]` — consistent, visible, non-crashing degradation.

### N9 — `(ValueError, ZeroDivisionError): logger.debug` for Market Line Parse

In `_training_data.py` and `batch_sim_tasks.py`. Debug severity is appropriate: games without odds data are expected; these aren't failures, they're expected gaps.

### N10 — Playwright Browser Lifecycle `logger.debug` with `exc_info=True`

Set during prior audit (H6). Browser cleanup failures are logged at debug with traceback — correct for teardown code.

### N11 — Auth Token Decode → HTTP 400

No internal traceback leaks; clean wrapping.

### N12 — `listFeatureLoadouts` Inner `.catch(() => ({ loadouts: [] }))`

The inner catch for loadouts is correct — loadouts are optional UI enrichment. The issue was the outer catch (fixed as H3).

### N13 — TypeScript `.catch(() => setHoldError(true))`

`web/src/app/admin/control-panel/page.tsx:488`. Sets error state — user sees an error indicator. Acceptable.

### N14 — `web/src/app/admin/users/page.tsx` `.catch(() => ({}))`

Returns empty objects, allowing destructuring defaults. Acceptable for admin UI optional data.

### N15 — ErrorBoundary `console.error`

`web/src/components/ErrorBoundary.tsx`. Logging to console from `componentDidCatch` is the React-recommended pattern.

### N16 — Proxy Route `console.error`

`web/src/app/proxy/[...path]/route.ts`. Logs the error then returns a 500 response — correct server-side error handling.

### N17 — `useStrategyBuilder.ts` Alert Refresh Fail

`console.warn("Failed to refresh alerts", err)` — non-critical background poll; warn-and-continue is appropriate.

### N18 — `packages/js-core/src/hooks/useStrategyBuilder.ts` Comment "Silently fail"

The comment is accurate: alert refresh is background enrichment. The warn log satisfies observability.

---

## Remediation Plan

### Immediate (done in this PR)
- [x] H1 — Add warning logs to silent DB deletes in `audit_data.py`
- [x] H2 — Add debug logs to silent registry lookups in `_model_routes.py`
- [x] H3 — Add `console.error` to empty outer `.catch` in `experiments/page.tsx`

### Short-term (next sprint)
- [x] M1 — Upgrade `model_service.py:210` pass → `logger.warning` with path and exc_info
- [x] M2 — Add `logger.warning` to `golf/client.py` settings load failure
- [x] M3 — Add `logger.debug` to NBA PBP probe miss; `logger.warning` on early abort

### Medium-term
- [ ] M5 — Add circuit breaker ceiling to realtime poller (max 20 failures before alert)
- [ ] Add Prometheus counter to circuit breaker trips for dashboarding

### Low Priority
- [ ] M7 — Upgrade date parse silences in `games.py` to `logger.debug`
- [ ] Consider structured result types (e.g. `Result[T, E]`) over `None` returns for model loading

---

---

## Second-Pass Findings (2026-04-19)

New findings not covered in the 2026-04-18 pass. Three fixed in-place.

### H-NEW-1 — `scraper/sports_scraper/persistence/games.py:69,81,92` — Silent Redis Cache Helpers (**Fixed**)

`_cache_get`, `_cache_set`, `_cache_delete` all catch `Exception` and `pass` with zero logging.
Redis outages produce no log output — all game-matching cache reads silently degrade to DB lookups across all Celery workers simultaneously, with no way to diagnose the slowdown.

**Fix:** Added `logger.debug(..., exc_info=True)` to each helper.

---

### H-NEW-2 — `api/app/services/pipeline/stages/finalize_moments.py:292` — pg_notify at debug (**Fixed**)

```python
except Exception:
    logger.debug("flow_published_notify_failed", extra={"game_id": game_id})
```

`pg_notify('flow_published', ...)` triggers all realtime SSE/WS delivery of new flow data. If this fails, all live subscribers stop receiving flow updates — only signal is a `debug` log invisible in production.

**Fix:** Upgraded to `logger.warning(..., exc_info=True)`.

---

### H-NEW-3 — `web/src/app/admin/control-panel/page.tsx:498–500` — Silent hold-toggle failure (**Fixed**)

```typescript
} catch {
  // ignore
}
```

The scheduler hold toggle catches failure silently — UI shows toggled state while server state is unchanged. Admin thinks schedulers are held when they aren't.

**Fix:** Changed to `setHoldError(true)` so existing error banner fires.

---

### M-NEW-1 — `api/app/realtime/manager.py:253` — `realtime_send_failed` at debug

`_dispatch_local` catches unexpected WS/SSE send failures at `logger.debug`. Sustained delivery failures (all connections dying) increment `_error_count` but produce no visible signal in production.

**Recommendation:** Upgrade to `logger.warning`.

---

### M-NEW-2 — `api/app/analytics/services/mlb_player_profiles.py:189` — Unlogged pitcher stats fallback

```python
except Exception:
    # Table may not exist yet or query failed — fall back
    return None
```

Zero logging on exception. Production query failures are invisible; only "table may not exist" case is expected and harmless.

**Recommendation:** Add `logger.warning("pitcher_statcast_query_failed", exc_info=True)`.

---

### M-NEW-3 — `scraper/sports_scraper/live_odds/redis_store.py:161` — Silent Redis scan failure

`get_all_live_keys_for_game` returns `[]` on exception with no logging. Redis scan failure makes the key list appear empty.

**Recommendation:** Add `logger.debug(..., exc_info=True)`.

---

## Appendix — Full Silent Pass Inventory (Production Code Only)

| File | Line | Exception | Context | Verdict |
|------|------|-----------|---------|---------|
| `scraper/scripts/audit_data.py` | 255 | `Exception` | Delete SportsGameFlow | **Fixed (H1)** |
| `scraper/scripts/audit_data.py` | 259 | `Exception` | Delete SportsGameTimelineArtifact | **Fixed (H1)** |
| `api/app/analytics/api/_model_routes.py` | 125 | `Exception` | File registry lookup | **Fixed (H2)** |
| `api/app/analytics/api/_model_routes.py` | 201 | `Exception` | File registry lookup | **Fixed (H2)** |
| `api/app/analytics/services/model_service.py` | 210 | `(JSONDecodeError, OSError)` | Metadata JSON load | M1 |
| `scraper/sports_scraper/golf/client.py` | 66 | `Exception` | Settings lazy-load | M2 |
| `scraper/sports_scraper/services/phases/boxscore_phase.py` | 236 | `Exception` | Error record cleanup | L8 — acceptable |
| `api/app/realtime/ws.py` | 128 | `(TimeoutError, CancelledError)` | Ping cancel on close | L1 — correct |
| `api/app/realtime/sse.py` | 80 | `CancelledError` | SSE client disconnect | L2 — correct |
| `api/app/dependencies/roles.py` | 158 | `ValueError` | URL parse for CORS | L3 — correct |
| `scraper/sports_scraper/utils/math.py` | 68 | `(ValueError, IndexError)` | Time string parse | L4 — correct |
| `scraper/sports_scraper/utils/provider_request.py` | 256 | `ValueError` | Int parse | L5 — correct |
| `api/app/tasks/_training_helpers.py` | 205 | `ImportError` | Optional LightGBM import | L6 — correct |
| `api/app/routers/sports/common.py` | 188 | `(ValueError, TypeError)` | Stat int conversion | L7 — correct |
| `infra/log-relay/server.py` | 152 | `KeyboardInterrupt` | Server shutdown | L10 — correct |

---

## Third-Pass Findings (2026-04-19)

Comprehensive re-audit covering pipeline stages, grader, grade-gate, regen flow, quality-review router, and realtime listener. Three fixed in-place.

### H-3P-1 — `api/app/realtime/listener.py:131` — Silent `break` on keepalive ping failure (**Fixed**)

```python
try:
    await conn.execute("SELECT 1")
except Exception:
    break   # ← no log
```

When the keepalive SELECT 1 fails, the inner loop silently breaks and triggers a reconnect. With no log entry at break-time, it is impossible to distinguish a clean idle reconnect from a sustained DB connectivity issue causing a reconnect storm. The reconnect itself logs the new connection attempt but not why the previous one dropped.

**Fix:** Added `logger.warning("listen_notify_keepalive_failed", exc_info=True)` immediately before `break`.

---

### H-3P-2 — `scraper/sports_scraper/persistence/games.py:43` — Truly silent `pass` on `pg_notify` (**Fixed**)

```python
except Exception:
    pass   # ← zero observability
```

The function docstring says "best-effort — never raises", which is the correct contract. However a silent `pass` means `pg_notify` failures are completely invisible in logs — impossible to diagnose during a LISTEN/NOTIFY outage investigation. The prior second-pass noted cache helper fixes at lines 69/81/92 but missed this one at line 43.

**Fix:** Changed to `logger.debug("pg_notify_game_update_failed", extra={"game_id": game_id}, exc_info=True)`.

---

### M-3P-1 — `scraper/sports_scraper/jobs/grader_task.py:156` — OTel metric emit logged at `debug` (**Fixed**)

```python
except Exception:
    logger.debug("grade_flow_task_otel_emit_failed", exc_info=True)
```

OTel metric emission failures are invisible in production (debug is filtered). A systematic instrumentation failure — broken metrics import, misconfigured exporter — would produce no visible signal while quality score histograms silently go dark.

**Fix:** Upgraded to `logger.warning("grade_flow_task_otel_emit_failed", exc_info=True)`.

---

### M-3P-2 — `scraper/sports_scraper/pipeline/grader.py:372` — LLM failure returns neutral 50.0

```python
except Exception:
    logger.warning("grader_t2_llm_call_failed", exc_info=True, ...)
    score = 50.0
    rubric = {}
```

Individual failures are logged at `warning` with `exc_info=True` — visibility is adequate. The risk is **systematic**: a prolonged Anthropic API outage causes every flow to receive `score=50.0`, which may pass or fail the grade gate for the wrong reasons. There is no counter or alert threshold to detect this condition.

**Risk:** Data integrity during LLM outage. No fix applied (logged correctly).

**Recommendation:** Add `tier2_grader_failed` OTel counter so an alert fires if failure rate exceeds threshold over a rolling window.

---

### M-3P-3 — `api/app/routers/admin/quality_review.py` — Regen enqueue failure after status write

```python
try:
    _enqueue_flow_regen(game_id)
except Exception:
    logger.warning("quality_review_reject_enqueue_failed", exc_info=True, ...)
```

The `QualityReviewQueue` row is committed with status `approved`/`rejected` before this call. If `_enqueue_flow_regen` fails, the row is permanently marked but no regen task runs — the flow stays in its current low-quality state with no UI signal. Logged at warning.

**Recommendation:** Make enqueue transactional with the status write, or return a 500 to force operator retry.

---

### M-3P-4 — `api/app/services/pipeline/stages/finalize_moments.py:307` — Celery `grade_flow_task` dispatch failure swallowed

```python
except Exception:
    logger.warning("grade_flow_task_dispatch_failed", exc_info=True, ...)
```

If Celery/Redis is unavailable when the pipeline finalizes, `grade_flow_task` is never dispatched. The flow is published but never graded — quality gate does not run. Stage still returns success. Logged at warning.

**Recommendation:** On dispatch failure, insert a `pending_grade` DB row that a sweep task drains.

---

### L-3P-1 — `api/app/realtime/listener.py:98,154` — Silent `pass` in shutdown/cleanup paths

Cleanup operations (`conn.close()` during `stop()`, listener removal in `finally`) catch and discard exceptions. Runs during shutdown or connection teardown only; reconnect loop covers any connection leaks.

**Verdict:** Acceptable. Upgrade to `logger.debug` if tracing reconnect issues becomes necessary.

---

### Note — New well-designed patterns confirmed (third pass)

| Pattern | File | Assessment |
|---------|------|-----------|
| Stage executor `except Exception → logger.error(exc_info=True) + StageResult(success=False)` | `executor.py` | Failure recorded in DB; caller gets typed result |
| Router `PipelineExecutionError → 400`, `Exception → logger.exception + 500` | `run_endpoints.py` | Correct HTTP error mapping; internals not leaked |
| Regen task `HTTPStatusError 4xx → return`, `5xx → raise` | `regen_flow_task.py` | Correct retry discrimination |
| `get_async_session` commit-on-success, rollback+reraise-on-exception | `api/app/db/__init__.py` | Verified: `autocommit=False`; explicit commit at context exit |
| Cache parse `(JSONDecodeError, KeyError, ValueError) → warning + fallthrough` | `grader.py:319` | Specific types; LLM call is authoritative fallback |

---

## Fourth-Pass Findings (2026-04-20)

Cleared all short-term and second-pass pending items. Six fixes applied in-place.

### M1 → Fixed — `api/app/analytics/services/model_service.py:210`

`(JSONDecodeError, OSError): pass` upgraded to `logger.warning("training_metadata_load_failed", extra={"path": path}, exc_info=True)`. Corrupt or missing training metadata sidecar files are now visible in logs.

---

### M2 → Fixed — `scraper/sports_scraper/golf/client.py:66`

`except Exception: pass` in DataGolf settings lazy-load upgraded to `_log().warning("datagolf_settings_load_failed", exc_info=True)`. Settings misconfiguration (wrong import path, missing attribute) is now diagnosable at init time rather than at the first auth-failing API call.

---

### M3 → Fixed — `scraper/sports_scraper/services/pbp_nba.py:151`

Added `logger.debug("nba_game_id_probe_parse_error", exc_info=True, extra={"game_id": game_id})` on each parse exception and `logger.warning("nba_game_id_probe_early_abort", ...)` when the 50-consecutive-miss threshold fires. Distinguishes legitimate end-of-season from parse failures that cause a truncated lookup table.

---

### M-NEW-1 → Fixed — `api/app/realtime/manager.py:253`

`_dispatch_local` send failure upgraded from `logger.debug` to `logger.warning` with `exc_info=True`. Sustained delivery failures (dead connections draining slowly) now produce visible signals in production log streams.

---

### M-NEW-2 → Fixed — `api/app/analytics/services/mlb_player_profiles.py:189`

`except Exception: return None` (zero logging) upgraded to `logger.warning("pitcher_statcast_query_failed", exc_info=True)`. DB query failures on the pitcher statcast table (schema drift, permissions) are now distinguishable from the expected "table not yet populated" case.

---

### M-NEW-3 → Fixed — `scraper/sports_scraper/live_odds/redis_store.py:161`

`except Exception: return []` (zero logging) upgraded to `logger.debug("live_odds_redis_scan_failed", extra={"game_id": game_id}, exc_info=True)`. Redis scan failures that silently return an empty key list are now visible at debug level (appropriate since this is a debugging helper, not a production data path).

---

### Remaining Open Items (from prior passes)

| ID | File | Description | Priority |
|----|------|-------------|----------|
| M5 | `api/app/realtime/poller.py` | No hard ceiling on consecutive DB failures; poller can loop indefinitely | Medium-term |
| M-3P-2 | `scraper/sports_scraper/pipeline/grader.py:372` | LLM outage causes every flow to receive neutral score=50.0 with no OTel counter alert | Medium-term |
| M-3P-3 | `api/app/routers/admin/quality_review.py` | Regen enqueue failure after status row commit — flow stuck in low-quality state | Medium-term |
| M-3P-4 | `api/app/services/pipeline/stages/finalize_moments.py:319` | Celery grade_flow_task dispatch failure swallowed — flow published but never graded | Medium-term |
| M7 | `scraper/sports_scraper/persistence/games.py` | Date parse silences → `logger.debug` | Low |

### Note — Pipeline stage `output.add_log` pattern (fourth pass)

`normalize_pbp.py` uses `output.add_log(f"Warning: ...", "warning")` for non-fatal stage failures (entity resolution persist, PBP snapshot create). This routes to the DB-persisted stage output log, not the application log stream. Acceptable: the stage executor captures and records all stage output, and these are best-effort instrumentation writes. If structured application log visibility is needed, add a parallel `logger.warning` call alongside `output.add_log`.
