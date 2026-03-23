# Error Handling & Suppression Audit

**Date:** 2026-03-23
**Scope:** Full repository (scraper, API, frontend, infrastructure)

---

## Section 1: Executive Summary

### Overall Assessment

**Prod posture has notable risk areas**, though the majority of suppressions are intentional resilience patterns appropriate for a data pipeline. The system prioritizes availability over strict correctness — individual game/record failures don't crash batch operations. This is the right design for a sports data pipeline where partial data is better than no data.

However, several patterns create **observability blind spots** where systemic failures look identical to "no data available," and a few areas have **data integrity risks** where failures are logged at the wrong severity level for alerting.

### Counts by Severity

| Severity | Count | Description |
|----------|-------|-------------|
| Critical | 3 | Silent game stub failures; JWT secret default; Redis lock bypass |
| High | 16 | Phase failures not propagating; odds/Redis silent empty; ML model degradation; social fail-open |
| Medium | 28 | Per-game loops without failure counters; warning-level DB errors; partial batch success; frontend silent catches; no error boundaries; Celery no acks_late |
| Low | 14 | Parse fallbacks; type guards; metadata-only losses; config defaults mitigated |
| Note | 10 | Intentional teardown, optional deps, cosmetic-only, positive findings |

### Counts by Category

| Category | Count |
|----------|-------|
| Data Integrity | 18 |
| Observability | 19 |
| Reliability | 14 |
| Security | 6 |
| Operational | 14 |

### Top 5 Issues

1. **Silent game stub failures in `poll_game_calendars`** — 5 bare `except: pass` blocks with zero logging. If `upsert_game_stub` has a systemic bug, every game fails invisibly for weeks.

2. **Redis lock returns dummy token on failure** (`utils/redis_lock.py:43`) — When Redis is down, ALL callers get "lock acquired." Distributed locking is completely defeated, enabling duplicate concurrent task execution.

3. **JWT secret has insecure default + ENVIRONMENT defaults to "development"** — If both env vars are missing in production, auth is fully compromised. `validate_env.py` does NOT validate JWT_SECRET against the known default.

4. **Phase failures don't propagate to run status** — Odds, boxscores, PBP, and advanced stats phases catch their own exceptions. Parent run reports "success" even when major phases fail.

5. **Live odds Redis returns empty on error** — Frontend receives empty odds data when Redis is down, indistinguishable from "no odds available." No error signal to consumers.

---

## Section 2: Critical & High Findings

### CRIT-1: Silent game stub failures in poll_game_calendars

- **File:** `scraper/sports_scraper/jobs/scrape_tasks.py`
- **Lines:** 259, 289, 323, 353, 386 (5 locations)
- **Pattern:** `except Exception: pass` — no logging, no counter
- **Trigger:** Any `upsert_game_stub` failure (constraint violation, team resolution, DB error)
- **Impact:** Game stubs silently not created. Calendar shows fewer upcoming games. No signal in logs.
- **Recommendation:** Add `logger.debug` + error counter per league. Log summary at end.

### CRIT-2: JWT secret insecure default + dev environment default

- **File:** `api/app/config.py:36,54`
- **Pattern:** `ENVIRONMENT` defaults to "development", `JWT_SECRET` defaults to known string
- **Trigger:** Missing env vars in production deployment
- **Impact:** All requests get admin role; tokens signed with known secret
- **Recommendation:** `validate_env.py` already checks but should hard-fail if `ENVIRONMENT=production` and `JWT_SECRET` is the default value.

### CRIT-3: Redis lock returns dummy token on failure

- **File:** `scraper/sports_scraper/utils/redis_lock.py:43`
- **Pattern:** `except Exception: return str(uuid.uuid4())  # Proceed anyway if Redis is down`
- **Trigger:** Redis connectivity failure (network, restart, OOM)
- **Impact:** ALL callers get "lock acquired" when Redis is down. Distributed locking defeated entirely. Multiple workers execute the same ingestion, odds sync, or social scraping concurrently.
- **Recommendation:** Return `None` (lock not acquired) on Redis failure. Callers already handle lock-not-acquired by skipping. Fail-closed is correct for locks.

### HIGH-1: Phase failures don't propagate to run status

- **Files:** `run_manager.py`, `boxscore_phase.py`, `pbp_phase.py`, `advanced_stats_phase.py`
- **Pattern:** Each phase catches its own exception, marks its job_run as "error", but doesn't re-raise. The parent `run()` method sees no exception and marks the run as "success."
- **Impact:** Runs with 0 games processed show as "success" in the admin UI.
- **Recommendation:** Track phase errors in summary dict. Mark run as "partial_success" if any phase failed but others succeeded.

### HIGH-2: Odds upsert failures counted as "skipped"

- **File:** `scraper/sports_scraper/odds/synchronizer.py:247-258`
- **Pattern:** `except Exception: session.rollback(); logger.warning(...); skipped += 1`
- **Impact:** DB errors (connection exhaustion, constraint violations) counted in same bucket as "no match." Systemic DB failure looks like "no odds data."
- **Recommendation:** Separate `error_count` from `skipped_count` in summary.

### HIGH-3: Live odds Redis returns empty on error

- **File:** `api/app/services/live_odds_redis.py:48,78,94`
- **Pattern:** `except Exception: logger.warning(...); return None/{}/[]`
- **Impact:** Frontend shows "no odds" when Redis is down. Consumer can't distinguish.
- **Recommendation:** Return a typed result that distinguishes "no data" from "error."

### HIGH-4: Ensemble probability providers fail silently

- **File:** `api/app/analytics/probabilities/probability_provider.py:328-335`
- **Pattern:** Both rule_based and ML providers wrapped in `except Exception: logger.warning(...)`
- **Impact:** Ensemble operates on partial data, producing biased probabilities with no signal.
- **Recommendation:** Log which providers succeeded. Include `providers_used` in response metadata.

### HIGH-5: Model registration failure swallowed after successful training

- **File:** `api/app/analytics/training/core/training_pipeline.py:362-365`
- **Pattern:** `except Exception: logger.warning("model_registration_failed")`
- **Impact:** Model trains but can't be used. Training job reports success.
- **Recommendation:** Propagate as training job error.

### HIGH-6: Pitch model load failure logged at DEBUG

- **File:** `api/app/analytics/core/simulation_engine.py:407-408`
- **Pattern:** `except Exception: logger.debug("pitch_models_load_skipped")`
- **Impact:** Simulation runs without pitch models. Degraded results. Invisible in prod logs.
- **Recommendation:** Log at WARNING. Include `degraded_mode: true` in simulation response.

### HIGH-7: Social task existence check returns False on DB error

- **File:** `scraper/sports_scraper/services/run_manager.py:53-55`
- **Pattern:** `except Exception: return False`
- **Impact:** DB connection issues allow duplicate social tasks → rate-limit exhaustion on X.
- **Recommendation:** Return True on error (fail-closed, not fail-open).

### HIGH-8: Job run activation failure leaves orphaned "queued" records

- **File:** `scraper/sports_scraper/jobs/scrape_tasks.py:107-109`
- **Pattern:** `except Exception: logger.warning(...); return None`
- **Impact:** UI shows job as perpetually "queued" (orphaned).
- **Recommendation:** Log at ERROR. Consider cleanup sweep for stale queued records.

### HIGH-9: Profile service DB query returns None silently

- **File:** `api/app/analytics/services/profile_service.py:399-401`
- **Pattern:** `except Exception: return None` with comment "Table may not exist yet"
- **Impact:** Simulation runs without pitcher profiles, degraded predictions.
- **Recommendation:** Log at WARNING with context about what data is missing.

### HIGH-10: PBP ingestion failures logged as warning, no failure counter

- **File:** `scraper/sports_scraper/services/pbp_nba.py:347-356` (and similar for all leagues)
- **Pattern:** `except Exception: session.rollback(); logger.warning(...); continue`
- **Impact:** If NBA API is down, every game fails at warning level. Summary reports 0 successes but doesn't report how many failed.
- **Recommendation:** Track `error_count` in return tuple.

### HIGH-11: Calibrator load failure serves uncalibrated odds

- **File:** `api/app/routers/model_odds.py:53-55`
- **Pattern:** `except Exception: return None` → response includes `"calibrated": false`
- **Impact:** Consumer that doesn't check `calibrated` field gets raw probabilities.
- **Recommendation:** Acceptable if documented. Consider 503 when calibrator unavailable.

### HIGH-12: _populate_external_ids failure silently skips all advanced stats

- **File:** `scraper/sports_scraper/services/phases/advanced_stats_phase.py:38-43`
- **Pattern:** `except Exception: logger.warning(...)`
- **Impact:** If ID population fails, 0 games match for advanced stats. Run reports success with 0 stats.
- **Recommendation:** Log at ERROR. Consider failing the phase.

---

## Section 3: Medium Findings Summary

| ID | File | Pattern | Impact |
|----|------|---------|--------|
| MED-1 | `persistence/boxscores.py:192` | Per-player upsert errors counted, not raised | Player data silently missing |
| MED-2 | `persistence/boxscores.py:304` | Player boxscore error caught after game marked enriched | Game shows as enriched without player data |
| MED-3 | `persistence/plays.py:115` | PBP snapshot creation failure → warning + None | Audit trail silently missing |
| MED-4 | `odds/client.py:204,285,402` | Non-200 HTTP returns empty list | API errors (429, 500) look like "no data" |
| MED-5 | `live_odds/closing_lines.py:121` | Provider fetch error → warning | Games go LIVE without closing lines |
| MED-6 | `nba_historical_ingestion.py:54,99,192` | Date/game errors → warning + continue | Backfill silently skips dates/games |
| MED-7 | `services/job_runs.py:184` | Celery revoke failure during eviction | Zombie tasks (DB says canceled, task runs) |
| MED-8 | `services/job_runs.py:223` | `_get_current_celery_task_id` bare except | Task ID lost outside Celery context |
| MED-9 | `golf/client.py:64-68` | API key load failure → `pass` | All golf API calls fail silently as "no data" |
| MED-10 | `realtime/poller.py:223,332,439` | Infinite retry loops with no circuit breaker | Persistent errors → infinite log noise |
| MED-11 | `analytics/training/core/model_evaluator.py:58` | `log_loss` calculation → `pass` | Training metrics incomplete |
| MED-12 | `analytics/training/core/training_pipeline.py:240` | Brier score → `pass` | Same |
| MED-13 | `tasks/batch_sim_tasks.py:343` | Per-game sim error → continue | Batch results incomplete, reported as success |
| MED-14 | `tasks/experiment_tasks.py:124` | Variant dispatch failure → continue | Experiment suite partially executed |
| MED-15 | `services/pipeline/stages/render_blocks.py:109` | OpenAI flow pass failure → return original blocks | Unpolished narrative in production |
| MED-16 | `analytics/inference/model_inference_engine.py:229` | Artifact load failure → warning | Falls back to rule-based, no consumer signal |
| MED-17 | `social_tasks.py:65` | Social completion reporting → warning | UI stuck at "dispatched to worker" |
| MED-18 | `mlb_advanced_stats_ingestion.py:266,366` | Pitcher/fielding parse errors → warning | Stats silently zeroed |

---

## Section 4: Categorization

### Acceptable Prod Notes (No Action Needed)
- Playwright browser teardown `except: pass` (3 locations)
- Optional dependency guards (nflreadpy, playwright)
- Parse/type guards returning None (time parsing, int coercion)
- Golf logger fallback
- Celery task revocation best-effort
- WebSocket ping loop `except: pass`
- Password verification returning False on malformed hash

### Acceptable But Should Be Documented
- Phase-level error isolation (odds/boxscores/PBP fail independently)
- Per-game commit/rollback pattern
- Redis lock preventing concurrent execution
- Circuit breaker patterns (advanced stats 5-failure limit, Playwright, odds credit check)
- `only_missing` skip logic

### Acceptable But Needs Better Telemetry
- **All per-game loops** need `error_count` in their summary
- **Odds synchronizer** needs separate error vs skip counters
- **Live odds Redis** needs a way to signal "error" vs "no data"
- **ML ensemble** needs `providers_used` metadata
- **Batch sim / backtest** should report `games_failed` alongside `games_processed`
- **Poller loops** need circuit breakers for persistent errors

### Should Be Tightened Before Prod
- `poll_game_calendars` bare `except: pass` → add logging
- `_social_task_exists_for_league` → fail-closed (return True on error)
- Simulation engine pitch model load → log at WARNING, add `degraded_mode`
- Model registration failure → propagate as training error
- `_populate_external_ids` failure → log at ERROR

### High Risk / Hidden Failure
- JWT secret default + ENVIRONMENT default combination
- Phase failures not reflected in parent run status

### Security-Sensitive
- `AUTH_ENABLED` bypass grants admin
- `API_KEY` not validated in development mode
- `pickle.load` for ML model artifacts (`# noqa: S301`)

### Data Loss / Corruption Risk
- Silent game stub failures (5 bare pass blocks)
- Per-player upsert errors not propagated
- Odds upsert failures counted as "skipped"

### Observability Blind Spots
- Per-game error counts not in summaries
- WARNING used for DB write failures (should be ERROR for alerting)
- Pitch model load at DEBUG level
- WebSocket send failures at DEBUG level
- Poller loops with infinite retry

---

## Section 5: Environment Review

### Where Prod Is Quieter Than Dev
- `AUTH_ENABLED=false` only allowed in development (default True)
- `API_KEY` validation skipped in development
- `validate_env.py` enforces stricter checks in production (no localhost URLs, no default credentials)

### Where Prod May Be More Permissive
- If `ENVIRONMENT` env var is missing, defaults to "development" → auth bypass
- If `JWT_SECRET` is missing, uses known default → token forgery
- Startup validation catches both of these, but only if `validate_env.py` runs before the app accepts requests

### Where Prod May Fail Open
- `_social_task_exists_for_league` returns False on error → allows duplicate work
- Redis errors in live odds → returns empty data → frontend shows "no odds"
- ML provider failures → ensemble uses partial data → biased predictions

### Where Prod May Hide Actionable Errors
- Phase failures hidden from parent run status
- Odds upsert errors counted as "skipped"
- Per-game loop errors not counted in summaries
- Pitch model load logged at DEBUG

### Assessment
Environment gating is **mostly reasonable**. The critical gap is the ENVIRONMENT/JWT_SECRET default combination — both defaulting to insecure values means a deployment that forgets to set env vars silently runs in an insecure state. The startup validator catches this but should be hardened with a runtime assertion.

---

## Section 6: Recommended Remediation Plan

### Quick Wins (< 1 hour each)

1. **Add logging to `poll_game_calendars` bare pass blocks** — Replace `except Exception: pass` with `except Exception: logger.debug("game_stub_error", ...); error_count += 1`. Add summary log at end of each league block.

2. **Fix `_social_task_exists_for_league` to fail-closed** — Change `return False` to `return True` on exception. Prevents duplicate social task dispatch when DB is down.

3. **Upgrade pitch model load from DEBUG to WARNING** — One-line change in `simulation_engine.py`.

4. **Add error_count to per-game loop summaries** — Add `errors` field to return tuples in boxscore, PBP, and advanced stats ingestion functions.

5. **Separate error vs skip in odds synchronizer** — Split `skipped` into `skipped` (no match) and `errors` (DB failure).

### Medium Effort (1-4 hours)

6. **Add "partial_success" run status** — When some phases succeed and others fail, mark the parent run as "partial_success" instead of "success." Requires adding a status value and updating the UI.

7. **Add `providers_used` to ML ensemble response** — Include which probability providers contributed to the result. Enables consumers to detect degraded predictions.

8. **Add circuit breakers to realtime pollers** — If a poller loop fails N consecutive times, back off exponentially instead of retrying at fixed intervals.

9. **Propagate model registration failure** — Change from `logger.warning` to re-raise. Training job should report "error" if the model can't be registered.

### High Value Hardening

10. **Runtime assertion for JWT_SECRET in production** — Add a check at app startup: if `ENVIRONMENT=production` and `JWT_SECRET` is the default value, refuse to start. Currently in `validate_env.py` but should be belt-and-suspenders in the config class.

11. **Typed error-or-data returns for Redis reads** — Replace `return None/[]/{}` with a result type that distinguishes "no data" from "error." Enables frontend to show appropriate messaging.

12. **Audit trail for suppressed failures** — Create a `sports_ingestion_errors` table that records per-game failures during backfills. Makes it possible to retry specific failed games without re-running entire date ranges.

### Documentation Gaps
- Document the phase error isolation design decision
- Document which log levels trigger alerts (if any alerting is configured)
- Document the per-game commit/rollback pattern and its trade-offs

### Test Gaps
- No tests verify that phase failures don't crash the parent run
- No tests verify error counters in summaries
- No tests for the `_social_task_exists_for_league` fail-open behavior

### Telemetry / Alerting Gaps
- No alerting on `logger.warning` patterns that indicate systemic failure
- No metric for "games attempted vs games succeeded" per run
- No health check for Redis connectivity from the API layer
- No metric for ML model load success/failure rate

---

## Verdict

**Prod posture has notable risk areas.** The system's resilience patterns are well-designed in principle — per-game isolation, phase independence, graceful degradation. But the execution has gaps:

1. **Observability is the biggest concern.** Systemic failures look identical to "no data available" in multiple places (odds, live odds, game stubs, advanced stats). An operator relying on the admin UI would not detect many failure modes.

2. **Security defaults are risky.** The ENVIRONMENT + JWT_SECRET defaulting to insecure values is one misconfigured deployment away from a breach. Startup validation mitigates but doesn't guarantee.

3. **Data integrity is mostly protected** by per-game commit/rollback, but the lack of error counters means a 100% failure rate in a batch looks identical to a 0% success rate in a batch with no candidates.

The top 6 quick wins (Redis lock fail-closed, logging in poll_game_calendars, fail-closed social check, pitch model log level, error counters, odds error/skip split) would meaningfully improve the operational posture with minimal effort.

---

## Appendix A: Frontend Findings

| ID | File | Pattern | Risk | Impact |
|----|------|---------|------|--------|
| F1 | `control-panel/page.tsx:448` | `.catch(() => {})` on hold status fetch | Medium | UI shows stale hold state |
| F2 | `control-panel/page.tsx:456` | `catch { // ignore }` on hold toggle | Medium | Operator action silently fails |
| F3 | `RunsDrawer.tsx:213` | `catch { }` on cancel job | Low | Cancel may silently fail |
| F4-F10 | Various analytics/golf pages | `catch { }` on polling/tab data | Low | Features silently degraded |
| F13 | All of `web/src/` | No React Error Boundaries | Medium | Render errors crash entire page |

**Positive:** Zero `eslint-disable`, `@ts-ignore`, or `@ts-expect-error` directives found.

## Appendix B: Infrastructure & Redis Findings

| ID | File | Pattern | Risk | Impact |
|----|------|---------|------|--------|
| R1 | `utils/redis_lock.py:43` | Dummy token on Redis failure | **Critical** | Distributed locks defeated |
| R2 | `celery_app.py:20-24` | `_is_held` returns False on Redis error | Medium | Hold bypassed during Redis outage |
| R3 | Celery config (both apps) | No `task_acks_late` setting | Medium | Task lost on worker crash |
| C4 | `docker-compose.yml:14-16` | DB defaults to `sports:sports` | Medium | `validate_env` checks `postgres:postgres` but not this |
| C5 | `docker-compose.yml:40` | Redis no-auth default | Medium | Redis unprotected if REDIS_PASSWORD unset |

## Appendix C: Prioritized Remediation Checklist

| # | Item | Effort | Severity |
|---|------|--------|----------|
| 1 | **Fix Redis lock to fail-closed** (return None, not dummy token) | 5 min | Critical |
| 2 | **Add JWT_SECRET validation** in production startup | 15 min | Critical |
| 3 | **Add logging to 5 bare `except: pass`** in poll_game_calendars | 15 min | Critical |
| 4 | Fix social task check to **fail-closed** | 5 min | High |
| 5 | Upgrade pitch model load log **DEBUG → WARNING** | 1 min | High |
| 6 | Add **error_count** to all per-game loop returns | 30 min | High |
| 7 | Separate **error vs skip** counters in odds synchronizer | 15 min | High |
| 8 | Add **"partial_success"** run status | 2 hrs | High |
| 9 | Propagate **model registration failure** as training error | 10 min | High |
| 10 | Add **React Error Boundaries** to main layout | 30 min | Medium |
| 11 | Add **`task_acks_late=True`** to Celery config | 5 min | Medium |
| 12 | Fix DB credential validation to catch `sports:sports` | 5 min | Medium |
| 13 | Add **circuit breakers** to realtime poller loops | 1 hr | Medium |
| 14 | Add `providers_used` to ML ensemble response | 1 hr | Medium |
| 15 | Typed error-or-data returns for Redis reads | 2 hrs | Medium |
