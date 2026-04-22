# Abend-Handling Audit

**Date:** 2026-04-22 (third pass)
**Scope:** `api/app/`, `scraper/sports_scraper/`, `web/src/`, `packages/`
**Supersedes:** prior same-day audit (10 findings) + second expanded pass (22 findings). All prior fixes re-verified; this pass applies two additional high/low-severity fixes in-place and updates status on items that have already been quietly resolved in the source.

---

## Executive Summary

The codebase has a solid foundation: explicit error hierarchies (`AppError` + global FastAPI handlers), structured JSON logging, a working circuit breaker on Redis live-odds reads, exponential backoff on webhook retry, and three-layer idempotency at every Stripe touch-point. The dominant error-handling pattern — broad `except Exception` that returns `None` from optional enrichment services (lineups, rosters, ML calibrators) — is consistent with the design doc's "simulate at degraded fidelity rather than fail hard" principle.

That said, **expanding the sweep into realtime, pipeline, ev/math, and Celery glue surfaces a cluster of silent-failure sites that the first audit missed**. None of them are exploitable or data-corrupting, but several are observability blind spots that will make a production incident harder than it needs to be.

### This pass
| Prior-audit items | Re-verified / updated | New fixes applied in-place |
|---|---|---|
| 32 | All | 3 (H1 session rollback wrapper, L6 timeline log-before-raise, confirmed M1 residuals already resolved upstream) |

### Fixes applied in this pass
| # | File | Change |
|---|------|--------|
| C | `api/app/db/__init__.py:68-81, 84-95` | `session.rollback()` now wrapped in its own `try/except` that logs `session_rollback_failed` at WARNING; original exception is preserved via the outer `raise`. Applied to both `get_db` and `get_async_session`. |
| D | `api/app/routers/sports/game_timeline.py:129-136` | `TimelineGenerationError` → `HTTPException` path now emits a `logger.warning("timeline_generation_failed")` with `game_id`/status/error before raising, so domain failures leave a trace. |

### Fixes applied in prior pass (re-verified still in place)
| # | File | Change |
|---|------|--------|
| A | `api/app/realtime/listener.py:101` | silent `pass` on `conn.close()` → `logger.debug("listen_notify_close_failed", exc_info=True)` |
| B | `api/app/realtime/listener.py:161-162` | silent `pass` on finally-block cleanup → `logger.debug("listen_notify_cleanup_failed", exc_info=True)` |

### Status updates discovered while verifying prior findings
- `api/app/realtime/ws.py:143-146` — no longer a silent `pass`; code now reads `except Exception: logger.exception("ws_error", extra={"conn": conn.id})`. **M1 ws.py residual resolved.**
- `api/app/realtime/sse.py:109-112` — `except asyncio.CancelledError: pass` is intentional (cancellation is the normal shutdown path); trailing `except Exception: logger.exception("sse_stream_error")` is in place. **M1 sse.py residual resolved.**

### Prior-audit fixes re-verified (still in place)
- `webhooks.py:262` — rollback failure logs `stripe_webhook_rollback_failed` ✅
- `audit.py:80` — audit-write failure at `ERROR` ✅
- `persistence/odds.py:30` — pg_notify failure at `DEBUG` with `exc_info` ✅
- `commerce.py:81,103` — catches `stripe.StripeError` (not just `AuthenticationError`) ✅

---

## Findings by Severity

Severity key — **High**: real reliability/security/compliance risk. **Medium**: observability blind spot that will bite under load. **Low**: best-effort path, fine as-is but could be tighter. **Note**: intentional by design.

### High

#### H1 — `get_async_session` / `get_db` rollback can mask the original exception — **FIXED in this pass**
**Files:** `api/app/db/__init__.py:68-81`, `:84-95`

Original pattern:
```python
except Exception:
    await session.rollback()   # if THIS raises, original exc is replaced
    raise
```

If `session.rollback()` itself raised (dead connection, driver-level failure), Python's "During handling of another exception…" semantics attach the rollback error as the `__context__`, but loggers and APM tools typically surface the outermost exception — so the *original* SQLAlchemy/business error was effectively lost.

Applied fix (duplicated at both call sites; centralizing would require a helper decorator and was judged to exceed the value):
```python
except Exception:
    try:
        await session.rollback()
    except Exception:
        logger.warning("session_rollback_failed", exc_info=True)
    raise
```

#### H2 — Every Celery scraper task uses `autoretry_for=(Exception,)`
**Files:** `scraper/sports_scraper/jobs/*.py` (60+ task definitions)

```python
@app.task(autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
```

`Exception` is a reasonable top-level catch for a scraper, but it also catches `ValueError`, `TypeError`, `KeyError`, `AttributeError`, etc. — the class of bugs that will *never* succeed on retry. The effect is:
1. Each programming error burns 3 retries + exponential backoff before it fails permanently (~minutes of wall clock and log noise per occurrence).
2. The real error signal is diluted because every bug shows up 4× in logs.

**Recommendation (not fixed):** narrow to the classes that are actually transient — `(requests.RequestException, httpx.HTTPError, asyncpg.PostgresConnectionError, redis.ConnectionError, TimeoutError, ConnectionError)` — and let programming errors fail fast. This is a moderate-blast-radius change (60+ call sites), so it belongs in a dedicated PR with a test that imports each task module.

#### H3 — EV math silently swallows `ValueError` in 10+ call sites
**Files:** `api/app/services/ev.py:226,283,305,310`; `api/app/routers/fairbet/ev_extrapolation.py:143,322,340,426,431,456`

All occurrences follow the pattern:
```python
try:
    prob = american_to_prob(odds)
except ValueError:
    continue   # or: return None
```

Data integrity concern: EV / +EV extrapolation feeds user-visible picks. A bad odds row that can't be parsed just disappears from the aggregate with no counter, no log, no alert. A bug that breaks *many* rows would halve the consensus without anyone noticing.

**Recommendation:** add a `logger.warning("ev_parse_skipped", extra={"odds": odds, "row_id": …})` on the first skip per request, and increment a Prometheus counter. This is higher-impact than it looks because the upstream odds normalizer is the canonical source of failures here.

---

### Medium

#### M1 — Realtime stream / SSE / WS catch-all with silent outcomes
**Files:**
- `api/app/realtime/listener.py:100-101` — **FIXED in this pass** (`pass` → `logger.debug`)
- `api/app/realtime/listener.py:161-162` — **FIXED in this pass** (`pass` → `logger.debug`)
- `api/app/realtime/ws.py:143-145` — `except Exception: pass` after an upstream `WebSocketDisconnect` branch; residual non-disconnect errors never surface.
- `api/app/realtime/sse.py:105-111` — final `except Exception: pass` after `TimeoutError`/`CancelledError` branches.
- `api/app/realtime/streams.py:114-115` — client close exception at `DEBUG` with `exc_info`.

`ws.py` and `sse.py` still have silent `pass` on the residual `Exception`. Realtime transport is one of the harder things to debug in production; every swallowed error there costs a lot during incident response. Minimum bar: `logger.debug("ws_close_unexpected", exc_info=True)`.

#### M2 — `realtime/streams.py` Redis retry has no bounded backoff ceiling signal
**File:** `api/app/realtime/streams.py:222-235`

Exponential backoff with `backoff = min(backoff * 2, MAX)` is correct, but there's no counter or "max consecutive failures" log that would let oncall distinguish "Redis blipped for 2s" from "Redis has been down for 20 minutes." Recommendation: log at `WARNING` after N consecutive backoff cycles, or wire into `CircuitBreakerRegistry` like `live_odds_redis.py` already does.

#### M3 — Scraper admin-hold fails open on Redis outage
**File:** `scraper/sports_scraper/celery_app.py:25-36`

```python
except Exception:
    logger.warning("admin_hold_check_failed", exc_info=True)
    return False   # "hold not active" → task proceeds
```

Documented and intentional (tasks proceed rather than stall when Redis blips). But the hold is also the mechanism used to pause scraping during deploys/DB migrations — under that scenario, "fail open" means a deploy with a Redis outage silently bypasses the safety. Flag for Phase 9 architectural decision (fail-open vs fail-closed per use case).

#### M4 — `odds_core._safe_game_meta_options` silently degrades to N+1 in tests/dev
**File:** `api/app/routers/fairbet/odds_core.py:15-28`

The function wraps `selectinload(...)` in try/except; on failure it returns `()` (no eager loading). In production it additionally logs an ERROR. The intent is documented ("tolerating partial mapper state in tests"), but the downside is real: if a rename ever breaks the relationship attribute, prod pages would silently drop to N+1 queries and the only signal would be a slow endpoint. A counter-metric (`game_meta_options_degraded_total`) would give a reliable tripwire without noise.

#### M5 — OpenAI client catches `Exception` broadly
**File:** `api/app/services/openai_client.py:92,104,111,140`

Mixes `json.JSONDecodeError` (correct) with `except Exception: logger.exception(...)` (too broad). A `TypeError` from a new SDK version would be logged identically to a network blip. Recommendation: catch `(httpx.HTTPError, openai.APIError, json.JSONDecodeError, ValueError)` and let the rest propagate.

#### M6 — Training pipeline ML failures are unrecoverable
**File:** `api/app/analytics/training/core/training_pipeline.py:240,368`

`except Exception as exc: logger.exception(...)` — logs well, but there is no Celery retry wrapper and no dead-letter. A transient S3/DB hiccup during training kills the run. Acceptable if trainings are scheduled on a cron, less so if they're user-triggered; worth wiring to Celery's retry.

#### M7 — Web admin UI: 80+ catch blocks that only call `setError(...)`
**Files:** widespread — `web/src/app/admin/**/page.tsx`

Pattern (`golf/pools/page.tsx:30`, `control-panel/page.tsx:66`, etc.):
```ts
catch (err) { setError(err instanceof Error ? err.message : String(err)); }
```

UX is fine — the admin sees the error — but there is no client-side telemetry (Sentry / Datadog RUM) capturing the event, so errors that hit real operators are invisible to engineering. Frontend error tracking is the Phase-9 hardening entry already on the roadmap; this is the concrete lever.

Two cases are slightly worse than the majority:
- `web/src/app/admin/analytics/experiments/page.tsx:145` — `.catch(() => ({ loadouts: [] }))` returns empty fallback with **no** log, **no** user-visible error. Silent.
- `web/src/app/admin/analytics/experiments/page.tsx:154` — logs to `console.error` only.

#### M8 — `circuit_breakers` admin router has nested silent pass
**File:** `api/app/routers/admin/circuit_breakers.py:135-137`

Two stacked `except Exception:` blocks, the outer one silent. Restructure into a single handler with explicit logging.

#### M9 — `probability_provider` / `probability_resolver` broad `Exception` → `None`
**Files:** `api/app/analytics/probabilities/probability_provider.py:362,368`; `probability_resolver.py:160,187`

Consistent with the "optional enrichment degrades to None" pattern, but these sit between the ML inference and the user-visible simulation result. A Prometheus counter on the degradation path is strongly recommended — right now the only signal is log-diving.

---

### Low

#### L1 — Analytics enrichment services (`mlb_*`, `nba_*`, `nhl_*`, `ncaab_*`) — broad `Exception` → `None` / `[]`
Consistent, intentional, covered by prior audit. Recommendation repeated: verify `exc_info=True` on every warning in these files (some are missing it, making root-cause diagnosis harder).

#### L2 — `model_odds.py:53-55` calibrator load returns `None` on any failure
Good logging with `exc_info`. Same degradation pattern as M9 — add a counter.

#### L3 — `services/pipeline/executor.py:442-449` logs ERROR then re-raises
Parent handler logs again. Results in duplicate stack traces in logs. Cosmetic.

#### L4 — `club_branding.py:55-56` — `except Exception: raise ValueError("invalid URL")`
Should be `except (ValueError, TypeError, AttributeError)`. Unlikely to matter in practice.

#### L5 — `live_odds_redis.py:81-86` — exception string returned to caller in error tuple
`return None, f"redis_error: {exc}"` — the `exc` render can leak implementation details. Low risk because the consumer stringifies it server-side, but sanitize-or-enum would be cleaner.

#### L6 — `routers/sports/game_timeline.py:131-136` — domain error → `HTTPException(400)` with no log — **FIXED in this pass**
A `logger.warning("timeline_generation_failed", …)` with the `game_id`, status code, and error message is now emitted before the `HTTPException` is raised.

---

### Note (intentional / acceptable by design)

| Topic | Location | Why it's fine |
|---|---|---|
| Auth returns 200 on email-send failure | `routers/auth.py:280-291,375-378` | User-enumeration protection; logs WARNING. |
| Webhook attempt record is best-effort | `tasks/webhook_retry.py:135-154` | Attempt table is audit, not idempotency source. |
| `audit._write` catches everything | `services/audit.py:62-84` | Module is documented fire-and-forget; gap (no DLQ) noted below. |
| `_notify_odds_update` best-effort | `scraper/.../persistence/odds.py:22-30` | pg_notify is a performance nicety, not load-bearing. |
| `circuit_breaker_registry.py:88` `queue.Empty: continue` | as designed | Empty queue is the happy path. |
| `billing.py:92` `except stripe.StripeError` | as designed | Narrow catch at the right layer. |
| `inference_cache.py:58` logs then re-raises | as designed | Cache visibility without swallowing. |
| `services/email.py:106-111` logs and re-raises | as designed | Email failures must bubble; no suppression. |
| Environment-based log level `INFO` vs `DEBUG` | `logging_config.py:84` | Standard practice. |
| Migrations have no try/except | `alembic/versions/*.py` | Alembic provides transactional DDL isolation. |

---

## Categorisation Summary

| Category | Count | Notes |
|---|---|---|
| Fixed in-place this pass | 2 | H1 (db rollback masking) + L6 (timeline log-before-raise) |
| Previously resolved in-source, confirmed this pass | 2 | M1 residuals in `ws.py` and `sse.py` already log via `logger.exception` |
| Fixed in earlier passes (re-verified) | 6 | webhooks.py, audit.py, odds.py, commerce.py, listener.py×2 |
| **High — still recommend fix soon** | 2 | H2 Celery autoretry scope, H3 EV silent skips |
| **Medium — needs telemetry/tightening** | 7 | M2–M9 (M1 fully resolved) |
| **Low — acceptable, polish when convenient** | 5 | L1–L5 (L6 resolved) |
| **Note — intentional** | 10+ | See table above |

---

## Gaps the prior audit missed

1. **Realtime transport layer entirely uncovered** — listener.py, ws.py, sse.py, streams.py together own six silent-or-nearly-silent catch sites. Two are now fixed; four remain.
2. **`db/__init__.py` session rollback masking** — the canonical session-lifecycle code has a subtle bug where a failing rollback hides the original exception.
3. **Celery scope** — 60+ `autoretry_for=(Exception,)` decorators were never enumerated. Not a vulnerability but a real operational cost.
4. **EV math silent skips** — 10 `except ValueError: continue/pass` in EV code, in pricing-adjacent paths.
5. **OpenAI client / pipeline executor / ML training** broad `Exception` catches without retry.
6. **Frontend observability gap** — 80+ `catch → setError` sites with no client-side error tracking.

---

## Remediation Plan

### Immediate (applied across passes)
- [x] `listener.py:101` — silent `pass` → `logger.debug("listen_notify_close_failed", exc_info=True)` (prior pass)
- [x] `listener.py:161-162` — silent `pass` → `logger.debug("listen_notify_cleanup_failed", exc_info=True)` (prior pass)
- [x] **H1** — `db/__init__.py` `get_db` / `get_async_session` rollback wrapped in its own try/except to preserve the original exception (this pass)
- [x] **L6** — `game_timeline.py` timeline failures now logged at WARNING before raising `HTTPException` (this pass)
- [x] **M1 residuals** — re-verified `ws.py:143-146` and `sse.py:105-115` already log via `logger.exception` upstream; no additional action needed.

### Next sprint (high-impact, low-blast-radius)
- [ ] Audit `mlb_*`/`nba_*`/`nhl_*`/`ncaab_*` services for missing `exc_info=True`.

### Phase 7 (Operational Visibility) — per ROADMAP
- [ ] **H3** — add counter + first-occurrence warning for `american_to_prob` ValueError skips in `ev.py` and `ev_extrapolation.py`.
- [ ] **M4** — Prometheus counter `game_meta_options_degraded_total`.
- [ ] **M6** — Celery retry wrapper around `training_pipeline.py` job entry points.
- [ ] **M9** — counters on probability provider/resolver degradation paths.
- [ ] **M7** — wire a frontend error tracker (Sentry) into the admin UI; at minimum capture the experiments-page silent fallbacks.
- [ ] Add dead-letter mechanism for audit events (deferred from prior audit).

### Phase 9 (Hardening)
- [ ] **H2** — narrow `autoretry_for=(Exception,)` to transient-only exception tuple across all scraper tasks.
- [ ] **M2** — circuit-breaker wrapper for `realtime/streams.py` Redis retry loop.
- [ ] **M3** — revisit fail-open vs fail-closed for `celery_app._is_held()` with deploy-scenario in mind.
- [ ] **M5** — narrow `openai_client.py` catches to `(httpx.HTTPError, openai.APIError, json.JSONDecodeError, ValueError)`.
- [ ] **L5** — sanitize exception-string in `live_odds_redis.py` return tuple.

---

**Audit methodology:** ripgrep sweep for `except`, `catch (`, `autoretry_for`, `pass` inside except bodies, `.catch(`, environment-conditional log/raise patterns, and silent fallback returns (`return None`, `return []`, `return ()`). Every prior-audit finding was re-read in the current source. Two fixes applied in-place with matching updates to this report; the rest are documented for the owner to triage.
