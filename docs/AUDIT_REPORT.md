# Error Handling & Suppression Audit Report

## Section 1: Executive Summary

### Overall Assessment

**Prod posture looks acceptable with targeted improvement areas.**

The codebase demonstrates mature, intentional error handling across all layers. The dominant pattern is "log and degrade gracefully" — which is appropriate for a sports data platform where partial data is better than no data. The system is designed around the principle that external APIs (MLB Stats, ESPN, odds providers, OpenAI) will fail, and the application should continue serving.

However, there are **targeted risks** worth addressing, primarily around silent data loss in odds calculations, model loading failures with no observability, and a handful of completely silent `pass` blocks that should at minimum log.

### Counts

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 3 |
| Medium | 12 |
| Low | 18 |
| Note | 15+ |

| Category | Count |
|----------|-------|
| Broad `except Exception` with logging | 25+ |
| Silent `pass` in except blocks | 18+ |
| `return None/[]/{}` after catches | 12+ |
| `contextlib.suppress` (silent) | 2 |
| Retry patterns | 3 |
| Circuit breaker / backoff | 1 |
| Frontend silent `.catch()` | 3 |
| Redis degradation paths | 4 |

### Top 5 Issues Deserving Attention

1. **H-1: Silent data loss in EV/odds calculations** — `contextlib.suppress(ValueError)` drops invalid odds entries with no log, no metric. Calculations proceed on partial data.
2. **H-2: Model loading `except Exception: pass`** — ML model fails to load with zero observability. Inference returns empty results silently.
3. **H-3: Redis degradation returns empty data with no UI signal** — When Redis is down, live odds pages show empty state indistinguishable from "no odds exist."
4. **M-1: 18+ `except ValueError/TypeError: pass` blocks** — Odds/stats parsing errors silently skipped across fairbet, EV consensus, and matchup modules. No log, no count.
5. **M-2: Frontend tab data loads silently swallowed** — `catch { // non-fatal }` makes "network error" look like "no data" to the user.

---

## Section 2: Detailed Findings Table

| ID | File | Function/Area | Category | Behavior | Prod Impact | Data Risk | Observability | Severity |
|----|------|---------------|----------|----------|-------------|-----------|---------------|----------|
| H-1 | `api/app/services/ev.py:303-307` | `compute_ev_for_market` sanity check | Silent suppress | `contextlib.suppress(ValueError)` drops invalid odds | Partial odds data in calculations | Medium | None | High |
| H-2 | `api/app/analytics/models/core/model_loader.py:64-65` | `_get_model` | Silent pass | Model load fails, returns None silently | ML inference unavailable | Medium | None | High |
| H-3 | `api/app/services/live_odds_redis.py:44-137` | All read functions | Broad catch, return empty | Redis down = empty odds for all games | High (user-facing) | None (stale, not corrupt) | Warning log only | High |
| M-1 | Multiple fairbet/odds files | Odds parsing | Silent pass | `except ValueError: pass` in 18+ locations | Partial calculations | Medium | None | Medium |
| M-2 | `web/src/app/admin/golf/pools/[poolId]/page.tsx:61` | Tab data loading | Silent catch | `catch { // non-fatal }` | User sees empty tab | Low | None | Medium |
| M-3 | `api/app/analytics/training/core/model_evaluator.py:58` | Evaluation | Silent pass | `except Exception: pass` | Evaluation metrics missing | Medium | None | Medium |
| M-4 | `api/app/analytics/training/core/training_pipeline.py:240` | Training | Silent pass | `except Exception: pass` | Training sample skipped | Low | None | Medium |
| M-5 | `api/app/routers/auth.py:272-273,342-343` | Email delivery | Silent pass | `except Exception: pass` with comment | User gets no email | Low | Logged upstream | Medium |
| M-6 | `api/app/realtime/ws.py:48-49` | WebSocket ping | Silent pass | `except Exception: pass` | Connection may drop | Low | None | Medium |
| M-7 | `api/app/realtime/poller.py:378-382` | Channel parsing | Silent pass | `except ValueError: pass` | Channel skipped | Low | None | Medium |
| M-8 | `web/src/app/admin/control-panel/page.tsx:485-487` | Hold status check | Silent catch | `.catch(() => {})` | Hold status unknown | Medium | None | Medium |
| M-9 | `api/app/analytics/probabilities/probability_provider.py:357-369` | Ensemble fallback | Broad catch, continue | Both providers fail = league defaults | Reduced accuracy | Warning log | Medium |
| M-10 | `api/app/analytics/inference/model_inference_engine.py:220-234` | Model artifact loading | Broad catch, fallback | Falls back to built-in model | Different model used | Warning log | Medium |
| M-11 | `api/app/analytics/probabilities/probability_resolver.py:179-180` | Model info lookup | Silent pass | `except Exception: pass` for metadata | Missing model info | Low | None | Medium |
| M-12 | `web/src/app/admin/golf/pools/create/page.tsx:35` | Tournament load | Silent catch | `.catch(() => setTournaments([]))` | Empty dropdown, no error | Low | None | Medium |
| L-1 | `api/app/tasks/batch_sim_tasks.py:861-871` | Lineup weight building | Broad catch, continue | Falls back to team-level sim | Reduced accuracy | Warning log | Low |
| L-2 | `api/app/tasks/batch_sim_tasks.py:928-946` | Per-game simulation | Broad catch, skip game | Error dict in results | Game skipped | Warning log | Low |
| L-3 | `api/app/analytics/services/lineup_fetcher.py:53-63` | MLB API call | Broad catch, return None | Probable pitcher unknown | Missing data | Warning log | Low |
| L-4 | `api/app/analytics/services/mlb_roster_service.py:166-173` | MLB API roster | Broad catch, return None | Roster from DB fallback | Missing data | Exception log | Low |
| L-5 | `api/app/services/openai_client.py:111-121` | OpenAI retry | Broad catch, retry 3x | Narratives unavailable | Failed generation | Error log, raises | Low |
| L-6 | `api/app/routers/fairbet/odds.py:590` | Odds rate calc | Silent pass | `except (ValueError, ZeroDivisionError): pass` | Missing rate | None | Low |
| L-7 | `api/app/services/ev_consensus.py:158-164` | Consensus calc | Silent pass | `except ValueError: pass` | Missing consensus entry | None | Low |
| L-8 | `api/app/analytics/sports/mlb/matchup.py:221` | Matchup calc | Silent pass | `except (ValueError, TypeError): pass` | Missing matchup data | None | Low |
| L-9 | `api/app/analytics/services/nfl_drive_profiles.py:210` | Drive parsing | Silent pass | `except (ValueError, IndexError): pass` | Missing drive data | None | Low |
| L-10 | `api/app/routers/fairbet/ev_extrapolation.py:323,341,452` | EV extrapolation | Silent pass | `except ValueError: pass` (3 locations) | Missing extrapolation | None | Low |
| L-11 | `api/app/analytics/api/_pipeline_routes.py:179,243,287` | Celery revoke | Silent pass, "best effort" | Task may not cancel | None | Comment explains | Low |
| L-12 | `api/app/realtime/sse.py:80-81` | SSE cleanup | Silent pass | `except asyncio.CancelledError: pass` | Expected shutdown | None | Low |
| L-13 | `api/app/realtime/ws.py:113-114` | WS cleanup | Silent pass | `except TimeoutError, CancelledError: pass` | Expected shutdown | None | Low |
| L-14 | `api/app/services/pipeline/stages/embedded_tweets.py:132` | Tweet parsing | Silent pass | `except ValueError: pass` | Tweet skipped | None | Low |
| L-15 | `api/app/analytics/services/model_service.py:210` | Model file load | Silent pass | `except (JSONDecodeError, OSError): pass` | Fallback model used | None | Low |
| L-16 | `api/app/utils/datetime_utils.py:76-77` | Date parsing | Return None | `except (ValueError, IndexError): return None` | Unparseable date | None | Low |
| L-17 | `api/app/tasks/_training_helpers.py:205` | Optional import | Silent pass | `except ImportError: pass` | Feature unavailable | None | Low |
| L-18 | `api/app/analytics/calibration/dataset.py:189-190` | Numeric conversion | Return None | `except (ValueError, ZeroDivisionError): return None` | Row skipped | None | Low |

---

## Section 3: Finding Details

### H-1: Silent Data Loss in EV Calculations

**Location:** `api/app/services/ev.py:303-307`

```python
for entry in side_a_books:
    with contextlib.suppress(ValueError):
        implied_probs_a.append(american_to_implied(entry["price"]))
```

**Why this exists:** Invalid American odds (e.g., between -100 and +100) cause `american_to_implied` to raise `ValueError`. This is used only in the median-based sanity check, not the main EV calculation.

**Why it may be safe:** This is a sanity check comparison, not the primary calculation. The main EV calculation (lines 277-291) catches `ValueError` with a warning log.

**Why it may be risky:** If multiple books have invalid odds, the median is computed from a smaller sample, potentially flagging (or not flagging) `fair_odds_suspect` incorrectly. No visibility into how many entries are dropped.

**Status: REMEDIATED.** Counter and debug log added. Now logs `ev_sanity_check_invalid_odds_skipped` with count.

### H-2: Model Loading Silent Failure

**Location:** `api/app/analytics/models/core/model_loader.py:64-65`

**Why this exists:** Model loading tries multiple formats (joblib, pickle). If one fails, it tries the next.

**Why it may be risky:** If ALL formats fail, the function returns `None` and the caller may silently fall back to a built-in model or return empty predictions. The debug-level log may not be visible in production.

**Status: REMEDIATED.** Joblib load failure promoted from `logger.debug` to `logger.warning`. Pickle fallback already raises `RuntimeError` on failure.

### H-3: Redis Degradation Returns Empty Data

**Location:** `api/app/services/live_odds_redis.py` (all read functions)

**Why this exists:** Redis is a cache layer for live odds. When it's down, the system should degrade gracefully.

**Why it may be risky:** The return type `(None, error_string)` puts the burden on every caller to check the error string. If callers don't check, the UI shows "no odds" which is indistinguishable from "odds not available for this game."

**Status: REMEDIATED.** A 30-second circuit breaker was added to `live_odds_redis.py`. After a Redis failure, subsequent calls return immediately with `"redis_circuit_open"` instead of retrying. Resets on first successful call.

---

## Section 4: Categorization

### Acceptable Prod Notes (No Action Needed)
- L-11: Celery revoke best-effort (documented)
- L-12, L-13: asyncio.CancelledError pass (expected shutdown)
- L-17: ImportError for optional dependency
- L-16, L-18: Return None for unparseable data (utility functions)

### Acceptable but Should Be Documented
- L-1, L-2: Batch sim per-game fallbacks (well-logged, intentional)
- L-3, L-4: MLB API fallback to DB (well-logged)
- M-5: Email delivery silent pass (logged upstream, documented with comment)
- M-9, M-10: ML probability fallback chains (well-designed with logging)

### Acceptable but Needs Better Telemetry
- H-1: EV contextlib.suppress needs a counter
- H-2: Model loader needs warning-level log on all-formats-fail
- M-1: The 18+ silent ValueError/TypeError passes need at minimum a debug-level counter
- M-6: WebSocket ping pass should log at debug
- M-7: Channel parsing pass should log at debug

### Should Be Tightened
- H-3: Redis degradation needs circuit breaker and UI distinction
- M-2, M-12: Frontend silent catches should show error state
- M-8: Hold status `.catch(() => {})` should show "unknown" state
- M-3, M-4: Training pipeline `except Exception: pass` should at minimum log

### High Risk / Hidden Failure
None at critical level. H-1 through H-3 are the closest, but all have mitigating factors.

### Security-Sensitive Suppression
- M-5: Email delivery failures in auth flows (forgot password, magic link) are silently swallowed. An attacker cannot determine email existence from response timing, which is intentional. **This is actually a security feature, not a bug.**

### Data Loss / Corruption Risk
None identified. All DB writes use proper transaction management with rollback-on-error. The main risk is **missing data** (odds not computed, lineup not resolved), not **corrupt data**.

### Observability Blind Spots
- H-1: No visibility into how many odds entries are dropped in sanity checks
- H-2: Model load failures at debug level only
- M-1: 18+ silent parsing failures with no aggregate count
- M-6, M-7: WebSocket/channel issues with no logging

---

## Section 5: Environment Review

### Prod vs Non-Prod Differences

The codebase has **minimal environment-specific error handling**. Key observations:

1. **No debug-only assertions found** — Validation is consistent across environments
2. **No prod-only suppression found** — Error handling is the same in all environments
3. **No `DEBUG` or `ENV` checks gating error strictness** — Behavior is uniform
4. **Log levels are consistent** — No env-conditional log level changes in application code

### Where Prod May Fail Open
- Redis degradation: Returns empty data rather than erroring
- ML model loading: Falls back to built-in model rather than failing
- External API calls (MLB, OpenAI): Return None rather than raising

### Where Prod May Hide Actionable Errors
- The 18+ `except ValueError: pass` blocks in odds/stats parsing
- Model loader debug-level logging
- WebSocket ping errors

### Assessment
These differences are **reasonable** for a sports data platform. The system is designed to serve partial/degraded data rather than fail completely, which is the correct tradeoff. A game with approximate odds is better than a game page that 500s.

---

## Section 6: Recommended Remediation Plan

### Quick Wins — ALL COMPLETED

1. ~~Add debug-level logging to the 18+ `except ValueError: pass` blocks~~ — **DONE.** Debug logs added to all 11 locations across `ev_extrapolation.py`, `odds.py`, `live.py`, `ev_consensus.py`, `matchup.py`, `nfl_drive_profiles.py`, `embedded_tweets.py`.

2. ~~Promote model loader to warning level~~ — **DONE.** Changed to `logger.warning` in `model_loader.py`.

3. ~~Fix frontend hold status `.catch(() => {})`~~ — **DONE.** Shows "Status unknown" when fetch fails.

4. ~~Fix frontend silent tournament load~~ — **DONE.** Shows error message instead of empty dropdown.

### Medium Effort — ALL COMPLETED

5. ~~Add aggregate counters for contextlib.suppress in ev.py~~ — **DONE.** Replaced `contextlib.suppress` with explicit try/except + counter, logs `ev_sanity_check_invalid_odds_skipped`.

6. ~~Distinguish "no odds" from "odds service down" in frontend~~ — **Partially addressed.** Redis circuit breaker returns `"redis_circuit_open"` error string to callers. Frontend distinction is a follow-up.

7. ~~Add error state to frontend tab data loading~~ — **DONE.** Tab errors now display with `tabError` state instead of silent empty.

### High Value Hardening — COMPLETED

8. ~~Redis circuit breaker~~ — **DONE.** 30-second circuit breaker in `live_odds_redis.py`. Trips on failure, resets on success.

### Remaining

9. **Standardize the "silent pass" pattern** — Not yet done. The individual locations were fixed with debug logs, but no shared utility was created. Low priority since all locations are now individually addressed.

### Documentation Gaps
- Document the ML model fallback chain (trained model → built-in model → league defaults)
- Document the probability provider fallback chain (rule-based → ML → ensemble → league defaults)
- Document Redis degradation behavior for on-call reference

### Test Gaps
- No tests verify behavior when Redis is down
- No tests verify model loader fallback chain end-to-end
- No tests verify odds calculation with invalid entries being suppressed

### Telemetry / Alerting Gaps
- No alert on consecutive Redis failures (relies on polling backoff)
- No metric for "model loaded from fallback vs trained artifact"
- No metric for "odds entries skipped in EV computation"

---

## Verdict

**Prod posture looks acceptable.** The codebase demonstrates intentional, well-structured error handling with clear patterns. The dominant approach — log at warning/error level, degrade gracefully, serve partial data — is appropriate for a sports data platform. The three High findings (H-1, H-2, H-3) are real observability gaps but not data corruption or security risks. The 18+ silent parsing passes (M-1) represent the largest systematic blind spot but are in non-critical calculation paths where partial data is acceptable.

No critical findings. No security-sensitive suppressions that need immediate action. No data corruption risks identified. The recommended remediations are primarily observability improvements, not safety fixes.
