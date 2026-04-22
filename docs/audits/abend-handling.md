# Abend-Handling Audit

**Date:** 2026-04-22
**Scope:** `api/app/`, `scraper/sports_scraper/`, `web/src/`, `packages/`
**Auditor:** Claude (claude-sonnet-4-6)

---

## Executive Summary

The codebase has a solid foundation: explicit error hierarchies, structured logging, a working circuit-breaker for Redis live-odds, exponential backoff on webhook retry, and idempotency at every Stripe touch-point. Most error suppression is either intentional and documented or confined to optional enrichment paths (analytics, lineup data, ML models) where degraded output is preferable to a hard failure.

Four issues required immediate in-place fixes:

| # | File | Severity | Fix Applied |
|---|------|----------|-------------|
| 1 | `api/app/routers/webhooks.py:261` | **Medium** | Added `logger.warning` on rollback failure (was silent `pass`) |
| 2 | `api/app/services/audit.py:72` | **Medium** | Upgraded audit-write failure log from `WARNING` → `ERROR` |
| 3 | `scraper/sports_scraper/persistence/odds.py:29` | **Low** | Added `logger.debug` on silent pg_notify failure |
| 4 | `api/app/routers/commerce.py:81,103` | **Medium** | Broadened Stripe catch from `AuthenticationError` → `StripeError` |

Three additional findings are classified as acceptable with telemetry recommendations.

---

## Detailed Findings

### Finding 1 — Silent pass on DB rollback failure (FIXED)
**File:** `api/app/routers/webhooks.py` line 261
**Severity:** Medium
**Risks:** Observability (rollback failures disappear entirely), reliability (transaction isolation)

```python
# BEFORE
try:
    await db.rollback()
except Exception:
    pass  # ← completely silent

# AFTER
try:
    await db.rollback()
except Exception:
    logger.warning("stripe_webhook_rollback_failed", exc_info=True)
```

The outer exception path already logs `stripe_webhook_db_error_enqueuing` and enqueues a Celery retry, so the webhook event is not lost. The inner silent `pass` meant rollback failures — which could leave a connection in a bad state — were invisible in logs. Now they emit a warning with full traceback for correlation.

---

### Finding 2 — Audit write failure logged at WARNING instead of ERROR (FIXED)
**File:** `api/app/services/audit.py` lines 72–77
**Severity:** Medium
**Risks:** Compliance/data integrity — audit events are the control plane record for payment and auth actions

The module is intentionally fire-and-forget (documented in the module docstring), so swallowing the exception is correct — callers on hot paths must not be blocked. However, a failed write to the `audit_events` table should be an ERROR, not a WARNING, because:

- Payment events (`subscription_activated`, `invoice_payment_failed`) may be required for dispute resolution.
- Auth events (`magic_link_issued`) may be required for incident forensics.
- WARNING-level messages are often filtered out in production log aggregators by default.

```python
# BEFORE
except Exception:
    logger.warning("audit_write_failed", exc_info=True, ...)

# AFTER
except Exception:
    logger.error("audit_write_failed", exc_info=True, ...)
```

**Remaining gap (no-code):** There is no dead-letter queue or retry for audit events. A transient DB outage will silently drop records. Acceptable for an MVP; add a local-fallback log line or a Celery retry in a future hardening phase.

---

### Finding 3 — Silent pg_notify failure with no logging (FIXED)
**File:** `scraper/sports_scraper/persistence/odds.py` lines 22–30
**Severity:** Low
**Risks:** Observability — realtime subscribers are not notified of odds updates

The function is intentionally best-effort (documented), but a completely silent `pass` makes it impossible to detect systematic failures (e.g., a user privilege that prevents `pg_notify`). Added a `logger.debug` call so the failure shows up in verbose logs without being noisy in production.

```python
# BEFORE
except Exception:
    pass

# AFTER
except Exception:
    logger.debug("odds_pg_notify_failed", extra={"game_id": game_id}, exc_info=True)
```

---

### Finding 4 — Stripe error handling too narrow in commerce.py (FIXED)
**File:** `api/app/routers/commerce.py` lines 81 and 103
**Severity:** Medium
**Risks:** Reliability — non-authentication Stripe errors surface as unhandled 500s rather than client-appropriate 503s

`billing.py` correctly catches `stripe.StripeError` (the base class for all Stripe API errors). `commerce.py` only catches `stripe.AuthenticationError`, meaning `RateLimitError`, `InvalidRequestError`, `APIConnectionError`, and others propagate as unhandled exceptions, producing 500 responses and full tracebacks rather than structured 503s.

```python
# BEFORE (both _get_or_create_stripe_customer and _create_checkout_session)
except stripe.AuthenticationError as exc:
    raise _stripe_503(exc) from exc

# AFTER
except stripe.StripeError as exc:
    raise _stripe_503(exc) from exc
```

`stripe.StripeError` is the root of all Stripe SDK exceptions; this is the correct catch site. `billing.py`'s pattern is now applied consistently to `commerce.py`.

---

### Finding 5 — Broad exception in lineup_fetcher without exc_info (Note — no fix)
**File:** `api/app/analytics/services/lineup_fetcher.py` lines 58–63
**Severity:** Low (acceptable)
**Classification:** Acceptable — MLB Stats API is optional enrichment; None return correctly degrades to team-level sim

The warning is logged but lacks `exc_info=True`, meaning the root cause (network error, 4xx, JSON parse error) is not captured. This makes debugging external API issues harder. No fix applied because this is analytics enrichment — a transient network error should not propagate. Recommend adding `exc_info=True` in a future polish pass.

---

### Finding 6 — Auth email delivery silently returns 200 OK (Note — intentional)
**File:** `api/app/routers/auth.py` lines 280–291 and 375–378
**Severity:** Note (acceptable by design)
**Classification:** Intentional — security requirement

`forgot_password` and `request_magic_link` intentionally return 200 even when email delivery fails. The docstring explains the reason: returning a different status code when the email fails would leak whether an email address is registered (user enumeration). The WARNING log is appropriate and monitored. This is correct security behaviour.

---

### Finding 7 — Celery hold check fails open (Note — intentional)
**File:** `scraper/sports_scraper/celery_app.py` lines 25–36
**Severity:** Note (acceptable)
**Classification:** Intentional fail-open

When Redis is unreachable, the admin hold is not enforced and scraper tasks proceed. The failure is logged as WARNING with `exc_info=True`. The docstring explicitly documents this decision: "if Redis is unreachable, allow tasks to proceed so ingestion is not silently blocked by transient infrastructure issues." This is a reasonable trade-off for a scraper (downtime cost > rare admin-hold bypass).

**Alternative to consider (no code change):** If the hold is used to prevent thundering-herd during deployments, fail-closed would be safer. Flag as an architectural decision for Phase 9 hardening.

---

### Finding 8 — Webhook attempt record is best-effort (Note — acceptable)
**File:** `api/app/tasks/webhook_retry.py` lines 135–154
**Severity:** Note (acceptable)
**Classification:** Intentional — explicitly documented in code comment

The comment reads: "Record attempt (best-effort — don't fail the task if this write fails)." The failure is logged as WARNING with the event ID for correlation. The delivery attempt table is audit/observability data, not idempotency data — the actual idempotency guarantee is in `processed_stripe_events`. Acceptable.

---

### Finding 9 — Analytics service broad excepts (Note — acceptable pattern)
**Files:** Multiple in `api/app/analytics/services/`
**Severity:** Note (acceptable)
**Classification:** Acceptable for optional enrichment paths

Multiple analytics services (`mlb_player_profiles.py`, `mlb_roster_service.py`, `nba_rotation_service.py`, etc.) catch broad `Exception` and return `None`. This is the correct pattern for optional enrichment: simulation runs at lower fidelity (team-level instead of lineup-aware) rather than failing hard. Each catch logs at WARNING with the relevant team/game ID. The simulation diagnostics surface degraded mode in the API response.

**Recommendation:** Add `exc_info=True` to catches that currently omit it, so root causes are captured without adding noise.

---

### Finding 10 — Audit service does not commit (Note — false alarm)
**File:** `api/app/services/audit.py` + `api/app/db/__init__.py`
**Severity:** None
**Classification:** Correct behaviour

The `audit._write()` function calls `db.add(AuditEvent(...))` inside `async with get_async_session() as db:`. Inspecting `get_async_session()` in `db/__init__.py:82–92` confirms the context manager calls `await session.commit()` on clean exit. The commit happens automatically; no explicit `await db.commit()` is needed.

---

## Categorisation Summary

| Category | Count | Action |
|----------|-------|--------|
| Fixed in-place | 4 | Applied — see findings 1–4 |
| Intentional / acceptable | 5 | Documented — see findings 5–10 |
| Needs telemetry (future) | 3 | Findings 2 (dead-letter), 5 (exc_info), 9 (exc_info) |

---

## Remediation Plan

### Immediate (applied in this audit)
- [x] `webhooks.py` — log rollback failure instead of silent pass
- [x] `audit.py` — upgrade audit-write failure to ERROR
- [x] `odds.py` — log pg_notify failure at DEBUG
- [x] `commerce.py` — catch `stripe.StripeError` instead of `AuthenticationError` only

### Phase 7 / Operational Visibility (future)
- [ ] Add a dead-letter mechanism for audit events (local file fallback or Celery retry with a separate queue)
- [ ] Add `exc_info=True` to `lineup_fetcher.py:58` and similar analytics catches that omit it
- [ ] Add aggregate alerting on WARNING-level exceptions from analytics services (e.g., alert if >10% of lineup fetches fail per hour)

### Phase 9 / Hardening (future)
- [ ] Evaluate fail-closed vs. fail-open strategy for `_is_held()` in scraper celery_app
- [ ] Add circuit-breaker pattern to `lineup_fetcher` and other external API calls (currently only `live_odds_redis.py` has a circuit breaker)
- [ ] Instrument broad-catch blocks in analytics services with Prometheus counters so failure rates are observable in Grafana without parsing logs
