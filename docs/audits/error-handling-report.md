# Abend Handling Audit

Date: 2026-05-23

Scope reviewed: `api`, `scraper`, `web/src`, `infra`, `scripts`, and CI/config files. The inventory scan excluded generated output, virtual environments, `node_modules`, coverage output, and tests for production-risk counts; test-only warning and coverage suppressions are called out where relevant.

Runtime sources checked include `api/main.py`, `api/app/config.py`, API dependencies and middleware, mounted routers, Celery app and scheduled tasks, polling helpers, webhook retry tasks, frontend API/SSE helpers, logging setup, telemetry setup, and active ingestion services.

## Section 1: Executive Summary

### Condensed Executive One-Pager

Verdict: **Prod posture has notable risk areas.**

Most suppressions are intentional resilience: generic API error envelopes, webhook retries, cache miss fallbacks, OpenAI text fallback, Stripe idempotency, Redis cache circuits, and frontend storage/SSE degradation are appropriate production behavior.

The notable remaining risks are concentrated in auth/audit boundaries, config hygiene, and ingestion visibility:

1. **Admin role derivation can elevate based on trusted admin origin plus API-key proxy context** (`api/app/dependencies/roles.py`). This must stay tightly scoped to admin routes and trusted edge behavior.
2. **Audit writes are fire-and-forget** (`api/app/services/audit.py`). Security-relevant audit events can fail without blocking the request.
3. **Missing external IDs still become low-noise no-op polling** (`scraper/sports_scraper/jobs/polling_helpers.py`). Active games can stay stale if ID population stalls.
4. **Unknown environment settings are ignored** (`api/app/config.py`). Misspelled production configuration can be missed without deploy lint.
5. **Redis rate-limit fallback weakens global enforcement** (`api/app/middleware/rate_limit.py`). This is acceptable for availability but should be alert-backed.

### Finding Counts

| Severity | Count |
| --- | ---: |
| Critical | 0 |
| High | 1 |
| Medium | 7 |
| Low | 11 |
| Note | 15 |
| **Total** | **34** |

### Category Counts

| Category | Count |
| --- | ---: |
| Exception handling / fallback defaults | 13 |
| Logging downgrade / observability suppression | 6 |
| Retries, backoff, circuit breakers, best-effort flows | 7 |
| Environment-specific strictness | 5 |
| Security or audit-sensitive handling | 3 |

### Inventory Snapshot

The static scan found 634 Python exception handlers in production-adjacent code and 349 broad handlers (`Exception`, bare `except`, or `BaseException`) outside tests/generated dependencies. The highest-density areas are scraper jobs, polling helpers, golf/social collectors, run management, realtime streams/listeners, live odds Redis, analytics pipeline routes, and admin pipeline endpoints.

That raw count is not itself a defect. Many handlers are deliberate retry, cleanup, idempotency, telemetry, cache, or frontend-degradation boundaries. Risk comes from handlers that convert hidden operational failures into apparent success, especially in scheduled ingestion and security/audit paths.

### Remediations Applied In This Pass

- `scraper/sports_scraper/celery_app.py`: scheduled task hold now fails closed when Redis hold state is unreadable.
- `scraper/sports_scraper/jobs/polling_tasks.py`: swallowed per-game polling errors now complete the job as `degraded` and store error counts/samples in `summary_data`.
- `api/app/routers/admin/circuit_breakers.py`: Playwright health now returns conservative open/unknown state when Redis circuit state cannot be read.
- `scraper/sports_scraper/logging.py`: scraper structured logs now redact sensitive fields before JSON rendering.
- Existing source comments now point directly to current finding IDs instead of obsolete section labels.

## Section 2: Detailed Findings Table

| ID | File path | Function / area | Category | Exact behavior | Trigger / failure mode | Current handling | Prod impact | Observability impact | Data integrity risk | Security risk | Reliability risk | Recommended disposition | Severity | Confidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AH-01 | `api/main.py` | global exception handler | Exception handling | Unhandled API exceptions become generic 500 JSON | Any uncaught request exception | Logs stack, increments metric, hides details from client | Appropriate | Good server logs, safe client response | Low | Low | Low | Keep | Note | High |
| AH-02 | `api/main.py` | `/healthz` | Dependency downgrade | Redis failure does not make healthz fail | Redis ping/read error | Logs warning, marks redis component error, keeps 200 if DB is healthy | Can report process healthy while Redis is impaired | Visible only if health payload is inspected | Low | Low | Medium | Document and alert on component status | Low | High |
| AH-03 | `api/main.py` | `/ready` | Dependency strictness | Readiness fails on DB or Redis error | DB/Redis check failure | Logs warning and returns 503 | Appropriate load-balancer signal | Good | Low | Low | Low | Keep | Note | High |
| AH-04 | `api/app/dependencies/auth.py`, `api/app/dependencies/consumer_auth.py` | API key dependencies | Environment strictness | Missing API keys are allowed only outside prod/staging | Key unset | Prod/staging returns 500; dev warns and permits | Appropriate dev ergonomics | Warning visible | Low | Low if prod env is correct | Low | Keep with env validation | Note | High |
| AH-05 | `api/app/dependencies/roles.py`, `api/app/config.py` | `AUTH_ENABLED=false` | Environment strictness | Auth-disabled mode grants admin role | Dev/test auth disabled | Prod/staging validator rejects this setting | Safe if validation runs before serving | Startup warning | Low | Medium if env validation bypassed | Low | Keep, test prod rejection | Note | High |
| AH-06 | `api/app/dependencies/roles.py` | `get_current_user` | Security-sensitive fallback | API-key-authenticated requests can become admin via admin origin/referrer heuristic | No JWT, admin-looking origin/referrer, API key already accepted | Returns admin principal; otherwise guest/user | If dependency is reused incorrectly, admin boundary can become origin-dependent | Logs are not emitted for this branch | Low | High | Medium | Add route-level tests and document trusted-edge assumptions | High | Medium |
| AH-07 | `api/app/middleware/rate_limit.py` | Redis rate limiting | Circuit/fallback | Redis limiter failure falls back to per-replica memory buckets | Redis unavailable/error | Logs error, increments metric, enforces local memory limiter | Global rate limit weakens across replicas | Good metric/log if monitored | Low | Medium abuse risk | Medium | Keep but alert on fallback metric | Medium | High |
| AH-08 | `api/app/otel.py`, `scraper/sports_scraper/telemetry.py` | OpenTelemetry init | Observability suppression | Missing OTLP endpoint disables tracing/metrics export | `OTEL_EXPORTER_OTLP_ENDPOINT` unset | Logs info once and installs no exporter | Fine for local; risky if prod forgets endpoint | Quiet after startup | Low | Low | Low | Document prod requirement; add deploy check if required | Low | High |
| AH-09 | `api/app/services/pipeline/metrics.py` | metrics helpers | Observability suppression | Missing OpenTelemetry package turns metrics into no-ops | ImportError | Debug log only; meter/counters return no-op behavior | Metrics can silently disappear in prod if package missing | Hidden at prod INFO log level | Low | Low | Medium | Promote missing metrics package to startup warning in prod | Low | Medium |
| AH-10 | `api/app/services/audit.py` | `AuditService.emit` | Audit best effort | Audit writes run in background and never block caller | DB/session/write failure | Logs `audit_write_failed`; request already succeeded | Security/audit trail can be incomplete | Error log only, no retry/dead-letter | Medium | Medium | Medium | Classify audit events; make critical ones durable | Medium | High |
| AH-11 | `api/app/routers/webhooks.py`, `api/app/tasks/webhook_retry.py` | Stripe webhooks | Retry/dead-letter | Handler failure enqueues retry; duplicate/unknown events are idempotent no-ops | DB/handler failure, duplicate, unknown event type | 202 on queued retry, 503 if retry enqueue fails; dead-letter after max retries | Well-designed resilience | Good metrics/logs | Low | Low | Low | Keep | Note | High |
| AH-12 | `api/app/routers/onboarding.py` | club claim notification | Best effort | Notification failure does not roll back submitted claim | Email/notification failure | Logs exception and still returns 201 | Claim persists, notification may be missed | Error log only | Low | Low | Low | Keep if notification is non-critical; add ops metric | Low | High |
| AH-13 | `api/app/services/catchup_context.py` | OpenAI catch-up enhancement | Fallback default | OpenAI/schema/JSON failures return deterministic template context | LLM unavailable, malformed output, missing client | Warning and deterministic fallback | User gets complete deterministic response | Good enough warning | Low | Low | Low | Keep | Note | High |
| AH-14 | `api/app/services/openai_client.py` | OpenAI client | Retry/downgrade | JSON decode and transient generation errors retry before raising | Bad model JSON or API failure | Warnings/errors per attempt, final raise | Caller decides fallback; catch-up currently falls back | Good logs | Low | Low | Low | Keep | Note | High |
| AH-15 | `scraper/sports_scraper/celery_app.py` | task hold check | Guardrail fail-closed | If Redis hold state cannot be read, scheduled tasks are treated as held | Redis unavailable or malformed hold read failure | Logs error and skips scheduled tasks; manual triggers still bypass hold | Operator hold intent is preserved | Error log is prominent | Low | Low | Low | Keep; alert on error log/metric if added | Low | High |
| AH-16 | `scraper/sports_scraper/utils/redis_lock.py`, `scraper/sports_scraper/jobs/polling_tasks.py` | polling lock | Guardrail fail-closed | Redis lock acquisition failure skips polling task | Redis lock error | Logs warning, returns no lock, task returns skipped | Data freshness can stall during Redis issue | Warning only; no failed job | Medium | Low | Medium | Emit metric and surface skipped-lock status in job run | Medium | High |
| AH-17 | `scraper/sports_scraper/jobs/polling_tasks.py` | `poll_live_pbp` | Partial failure degradation | Per-game PBP/boxscore errors are logged and task continues | Provider, parse, DB, or per-game errors | Rollback, warning with stack, continue loop, complete job as `degraded` with error count/samples | Stale/partial data is now visible in job status | Job status and summary data show degradation | Medium | Low | Medium | Keep improving with per-league metrics | Medium | High |
| AH-18 | `scraper/sports_scraper/jobs/polling_helpers.py` | missing external IDs | Silent/no-op default | Missing external IDs often return zero API calls and debug/no-op | Active game lacks provider ID | Skip PBP/boxscore polling for that game | Game can remain stale until ID population succeeds | Often debug only | Medium | Low | Medium | Promote repeated missing IDs to warning/metric | Medium | High |
| AH-19 | `scraper/sports_scraper/jobs/polling_helpers.py` | boxscore DB recovery | Retry then soft failure | Transient DB boxscore failures retry once, then return no update | DBOperationalError/InterfaceError or other DB failure | Rollback, warning, return `boxscore_updated=False` | Partial data without failed task | Warning only | Medium | Low | Medium | Count as degraded polling outcome | Medium | High |
| AH-20 | `scraper/sports_scraper/utils/provider_request.py` | provider rate/backoff wrapper | Backoff/default | Token bucket exhaustion, timeout, and provider 429 return `None` instead of raising | Rate limit/backoff/timeout | Logs warning/info and sets backoff | Data delayed but protects provider quota | Visible if logs watched | Low | Low | Low | Keep; document `None` contract | Low | High |
| AH-21 | `scraper/sports_scraper/services/job_runs.py` | job run completion/activation | State fallback | Missing/canceled job runs log and skip overwrite or start replacement run | Race, stale task, missing run row | Logs error/warning/info, avoids clobbering canceled state | Mostly safe queue hygiene | Logs only | Low | Low | Low | Keep; add metrics for unexpected missing runs | Low | Medium |
| AH-22 | `scraper/sports_scraper/celery_app.py` | worker startup/shutdown cleanup | Recovery | Stale running/pending runs are marked interrupted; cleanup failures do not crash worker | Worker start/stop, DB cleanup failure | Logs exception and continues startup/shutdown | Prevents stale status when healthy; cleanup failure may leave stale rows | Stack logged | Low | Low | Low | Keep | Note | High |
| AH-23 | `api/app/services/response_cache.py` | Redis response cache | Circuit/fallback | Cache read/write failures become misses and short cache circuit opens | Redis cache errors | Logs warning, bypasses cache | More DB/API load, no correctness issue | Visible warning | Low | Low | Low | Keep | Note | High |
| AH-24 | `web/src/app/proxy/[...path]/route.ts`, `web/src/lib/api/sportsAdmin/client.ts` | admin API proxy/client | Sanitization | Backend errors are sanitized before client display | Fetch/proxy/backend error | Server logs details; client gets generic message/correlation id | Good security posture | Good correlation id | Low | Low positive | Low | Keep | Note | High |
| AH-25 | `web/src/lib/hooks/useGameFilters.ts` | localStorage filters | Frontend suppression | localStorage read/write failures are ignored | Private mode/quota/blocked storage | Returns null or skips save | Filter persistence only affected | No central telemetry | None | None | None | Keep | Note | High |
| AH-26 | `web/src/lib/hooks/useGameFilters.ts`, `web/src/components/ErrorBoundary.tsx` | frontend UI errors | UI-only observability | API load/render failures show UI state or console error without central telemetry | Fetch/render exception | Sets local error or logs console | User sees failure; ops may not | Browser-only unless collected elsewhere | Low | Low | Low | Add browser telemetry for admin-prod | Low | Medium |
| AH-27 | `web/src/lib/api/sseBase.ts` | `safeEventSource` | Realtime fallback | EventSource construction failure returns `null` | Bad URL, browser/env SSE failure | Console warning; caller runs without live updates | UI may become stale until manual refresh/poll | Browser console only | Low | Low | Low | Add visible stale indicator where not already present | Low | Medium |
| AH-28 | `api/app/routers/golf/pools.py` | honeypot field | Intentional silent no-op | Bot-looking pool submissions return 201 without persistence | Honeypot field populated | Silent success | Good anti-abuse behavior | Intentionally quiet | Low | Low positive | Low | Keep | Note | Medium |
| AH-29 | `api/app/routers/admin/circuit_breakers.py` | circuit breaker status | Status fail-closed | Redis/circuit state read failure returns open/unknown health state | Redis read error | Logs warning and returns conservative open state with unknown health payload | Operator sees degraded dependency instead of false closed | Warning plus response payload | Low | Low | Low | Keep; add explicit status enum later if desired | Low | Medium |
| AH-30 | `api/app/realtime/streams.py`, `api/app/realtime/listener.py` | realtime stream processing | Drop/ack malformed events | Malformed stream entries are warned and acked/dropped; dispatch failures reconnect/back off | Bad Redis stream entry or websocket dispatch issue | Warning/drop or reconnect with thresholds | Lower risk because realtime routes are not currently mounted | Warnings/threshold logs | Low | Low | Low | Keep if unmounted; document before enabling | Low | Medium |
| AH-31 | `api/app/tasks/webhook_retry.py` | webhook delivery attempts | Best effort audit | Attempt-record write failure does not retry whole webhook | Attempt record insert failure after handler processed | Logs error and avoids duplicate handler side effect | Prevents duplicate processing; loses attempt audit | Error log only | Low | Low | Low | Keep; add metric | Note | High |
| AH-32 | `api/app/config.py` | settings model | Config defaulting | Unknown env vars are ignored via `extra="ignore"` | Misspelled env var or leftover config | App starts and ignores unknown setting | Config typo can be missed | No warning | Low | Low | Medium | Consider prod unknown-env lint in deploy scripts | Medium | Medium |
| AH-33 | `api/app/logging_config.py`, `scraper/sports_scraper/logging.py` | production log level | Log downgrade | Prod defaults to INFO while non-prod defaults DEBUG | `ENV=production` | Debug-only suppressions disappear | Normal, but debug-only fallbacks are invisible | Expected | Low | Low | Low | Keep; do not rely on debug for prod incidents | Note | High |
| AH-34 | `scraper/sports_scraper/logging.py` | scraper structured logs | Security/observability | Scraper structured logs redact known sensitive keys before JSON rendering | Any scraper log with secret-bearing extra field | Sensitive exact-key fields become `[REDACTED]` | Future accidental secret leakage risk is reduced | Good logs with sanitizer | Low | Low | Low | Keep; consider recursive redaction if nested extras appear | Note | Medium |

## Section 3: Finding Details

### AH-01: Generic API exception envelope

Location: `api/main.py` global exception handler.

Unhandled request exceptions are logged with stack trace, `api_exceptions_total` is incremented, and clients receive `{"detail": "Internal server error"}`. This is intentional and production-appropriate because it preserves server-side diagnostics without leaking internals. Keep it.

### AH-02: `/healthz` is softer than `/ready`

Location: `api/main.py` health endpoints.

Database failure makes `/healthz` return 503, but Redis failure is only included as a component error while the overall health response can stay `ok`. This is reasonable for process liveness, but production monitors must inspect the component payload or rely on `/ready` for dependency readiness. Add an operator note or alert on Redis component errors.

### AH-03: Readiness fails closed on dependencies

Location: `api/main.py` `/ready`.

Readiness returns 503 if DB or Redis checks fail. This is the correct strict signal for load balancers and deployments. No remediation needed.

### AH-04: Missing API keys are dev-permissive only

Location: `api/app/dependencies/auth.py`, `api/app/dependencies/consumer_auth.py`, `api/app/config.py`.

The auth dependencies allow unauthenticated requests only when API keys are unset outside prod/staging. Prod/staging validators reject missing or weak API keys. This is acceptable and intentional, assuming prod startup validation always runs.

### AH-05: Auth-disabled mode is constrained to non-prod

Location: `api/app/dependencies/roles.py`, `api/app/config.py`.

`AUTH_ENABLED=false` returns an admin-like principal for local/dev ease. The settings validator rejects this in `production` and `staging`. This is an acceptable development bypass. Keep tests around prod/staging rejection.

### AH-06: Admin role can depend on trusted origin when JWT is absent

Location: `api/app/dependencies/roles.py`.

For API-key-verified requests without JWT, admin-looking origin/referrer can produce an admin principal. This appears intentional for a server-side admin proxy, and the code rejects consumer keys in admin contexts. The risk is that reuse of `get_current_user` or trusted-forwarded-origin behavior outside intended routes could turn an origin header into an authorization boundary. Route-level tests and docs should prove that sensitive admin endpoints always require the intended dependency chain.

### AH-07: Redis rate limiter fallback weakens global enforcement

Location: `api/app/middleware/rate_limit.py`.

When Redis-backed rate limiting is enabled but Redis operations fail, the middleware logs an error, increments a fallback metric, and uses per-process memory buckets. This is a good fail-soft posture for availability, but global enforcement weakens across replicas. Production should alert on the fallback metric.

### AH-08: OpenTelemetry endpoint absence disables tracing

Location: `api/app/otel.py`, `scraper/sports_scraper/telemetry.py`.

When no OTLP endpoint is configured, tracing/metrics export is disabled with an info log. That is correct for local development. In prod it becomes an observability gap if the endpoint is accidentally omitted. Document the expected prod setting and consider deploy-time validation if traces are required.

### AH-09: Metrics helpers no-op if OpenTelemetry package is absent

Location: `api/app/services/pipeline/metrics.py`.

Import failure creates no-op meter/counter helpers and only logs at debug. In production, DEBUG is hidden by default, so metric loss could be silent. Promote this to a prod startup warning if pipeline metrics are expected.

### AH-10: Audit writes are fire-and-forget

Location: `api/app/services/audit.py`.

`AuditService.emit()` schedules an async write and never blocks the caller. `_write()` logs failures with `exc_info`, but there is no retry or dead-letter. This is acceptable only for low-value audit notes. Security-sensitive events should either be durable before success or sent to a retryable queue.

### AH-11: Stripe webhook retry handling is well-designed

Location: `api/app/routers/webhooks.py`, `api/app/tasks/webhook_retry.py`.

Invalid signatures fail closed, duplicates are idempotent no-ops, unknown events are debug-level no-ops, handler failures enqueue retries, and enqueue failure returns 503 so Stripe retries. The retry task dead-letters after bounded exponential attempts. Keep this pattern.

### AH-12: Club claim notifications are best effort

Location: `api/app/routers/onboarding.py`.

Claim persistence is committed before notification. Notification failure logs an exception and the API still returns 201. That is appropriate if the claim record is the source of truth. Add a metric or dashboard if missed notification is operationally meaningful.

### AH-13: OpenAI catch-up enhancement falls back to deterministic context

Location: `api/app/services/catchup_context.py`.

OpenAI client absence, malformed JSON, schema mismatch, or generation failure returns deterministic context. This is a healthy optional-AI fallback: user-visible behavior remains complete and deterministic.

### AH-14: OpenAI client retries before raising

Location: `api/app/services/openai_client.py`.

The client retries JSON decode failures and generation exceptions before raising. Callers such as catch-up context convert final failure into deterministic fallback. This is intentional and low risk.

### AH-15: Task hold fails closed on Redis read failure

Location: `scraper/sports_scraper/celery_app.py`.

`_is_held()` treats unreadable Redis hold state as held, logs an error, and skips scheduled tasks. Manual triggers still bypass the hold through the existing header path. This preserves operator guardrails during maintenance and removes the prior fail-open behavior.

### AH-16: Redis lock failure skips polling

Location: `scraper/sports_scraper/utils/redis_lock.py`, `scraper/sports_scraper/jobs/polling_tasks.py`.

Lock acquisition fails closed: polling returns skipped instead of running without a lock. That avoids duplicate work but can hide data freshness gaps if the skip is not visible in job status or metrics. Surface lock-skipped outcomes distinctly.

### AH-17: Polling records degraded completion after per-game failures

Location: `scraper/sports_scraper/jobs/polling_tasks.py`.

The polling task still catches per-game PBP and boxscore failures, rolls back, logs warnings, and continues so one bad game does not block the cycle. It now marks the job run as `degraded` when suppressed polling errors occurred and stores counts/samples in `summary_data`. The remaining risk is data freshness, not hidden success.

### AH-18: Missing external IDs become no-op polling

Location: `scraper/sports_scraper/jobs/polling_helpers.py`.

Several provider polling helpers return zero API calls when an active game lacks the required external ID. Some paths log only debug. This is safe for a single expected gap but risky when ID population stalls. Promote repeated active-game missing IDs to warning/metric.

### AH-19: Boxscore DB recovery returns soft no-update

Location: `scraper/sports_scraper/jobs/polling_helpers.py`.

Transient DB errors get a rollback/retry path, then return `boxscore_updated=False` rather than failing the job. This is reasonable resilience, but the containing job should reflect degraded output.

### AH-20: Provider request wrapper returns `None` for backoff/timeout

Location: `scraper/sports_scraper/utils/provider_request.py`.

Provider backoff, token exhaustion, timeout, and 429 responses return `None` with logs/backoff state. This is appropriate provider-friendly behavior, but the `None` contract should stay documented so callers do not treat it as "no data exists."

### AH-21: Job-run state handlers avoid clobbering cancellation

Location: `scraper/sports_scraper/services/job_runs.py`.

Missing runs, canceled runs, and unexpected queued statuses log and avoid overwriting operator intent. This is reasonable. Add metrics for unexpected missing runs if it recurs.

### AH-22: Worker startup/shutdown cleanup is best effort

Location: `scraper/sports_scraper/celery_app.py`.

Startup/shutdown cleanup marks stale runs interrupted but does not crash the worker on cleanup failure. This is acceptable because the alternative is blocking worker availability for metadata cleanup.

### AH-23: Response cache failures become misses

Location: `api/app/services/response_cache.py`.

Redis cache errors open a short local circuit and return cache misses. This trades performance for correctness and is production-appropriate.

### AH-24: Admin proxy/client sanitize backend errors

Location: `web/src/app/proxy/[...path]/route.ts`, `web/src/lib/api/sportsAdmin/client.ts`.

The proxy strips sensitive inbound headers, injects server-side API key if configured, logs internal errors server-side, and returns sanitized client errors with correlation IDs. This is intentional and healthy.

### AH-25: Filter persistence ignores localStorage failure

Location: `web/src/lib/hooks/useGameFilters.ts`.

Blocked/quota-failed localStorage reads and writes are ignored. Only UI preference persistence is affected. This is acceptable frontend resilience.

### AH-26: Frontend failures are not centrally collected

Location: `web/src/lib/hooks/useGameFilters.ts`, `web/src/components/ErrorBoundary.tsx`.

Some frontend failures set local UI error state or log to browser console only. Users see failures, but operators may not. Add browser telemetry if admin UI runtime errors matter in production.

### AH-27: SSE construction failure degrades to no live updates

Location: `web/src/lib/api/sseBase.ts`.

`safeEventSource()` catches EventSource construction errors and returns `null`. This protects render paths, but callers should show a stale/live indicator where realtime matters.

### AH-28: Honeypot submissions intentionally look successful

Location: `api/app/routers/golf/pools.py`.

Bot-looking requests with the honeypot field populated return 201 without persistence. This is intentionally quiet anti-abuse behavior and should remain quiet.

### AH-29: Circuit breaker status fails conservatively on status-store failure

Location: `api/app/routers/admin/circuit_breakers.py`.

When the Playwright circuit state cannot be read from Redis, the admin status surface now logs a warning and returns a conservative open/unknown health payload instead of defaulting to closed/zero failures. This avoids a healthy-looking status during a status-store outage.

### AH-30: Realtime malformed events are dropped

Location: `api/app/realtime/streams.py`, `api/app/realtime/listener.py`.

Malformed Redis stream entries are warned and acknowledged/dropped to keep fresh events moving; dispatch failures reconnect with backoff. This is acceptable if realtime remains non-authoritative. Document before enabling realtime routes as a production dependency.

### AH-31: Webhook attempt logging is best effort after handler success

Location: `api/app/tasks/webhook_retry.py`.

If the webhook handler has already succeeded, delivery-attempt record failure does not retry the whole webhook to avoid duplicate side effects. This is correct. Add a metric for lost attempt records.

### AH-32: Unknown environment settings are ignored

Location: `api/app/config.py`.

Pydantic settings use `extra="ignore"`, so misspelled or obsolete env vars do not fail startup. This keeps deploys tolerant but can hide config mistakes. A deploy-time env linter is safer than making runtime config brittle.

### AH-33: Production hides debug-only suppression breadcrumbs

Location: `api/app/logging_config.py`, `scraper/sports_scraper/logging.py`.

Production defaults to INFO while non-prod defaults DEBUG. This is normal, but production suppressions should not rely only on debug logs for detectability.

### AH-34: Scraper logs redact API-style sensitive fields

Location: `scraper/sports_scraper/logging.py`, compared with `api/app/logging_config.py`.

The scraper structured logger now redacts exact sensitive field names before JSON rendering, matching the API's basic redaction posture. This covers flat structured fields such as `api_key`, `authorization`, `token`, and `secret`. Recursive redaction can be added later if nested extras become common.

## Section 4: Categorization

### Acceptable Prod Notes

- AH-01: Generic API 500 envelope.
- AH-03: Readiness strict dependency check.
- AH-04: Dev-only missing API key allowance with prod validation.
- AH-05: Dev-only auth-disabled mode with prod validation.
- AH-11: Stripe webhook retry/dead-letter handling.
- AH-13: OpenAI catch-up deterministic fallback.
- AH-14: OpenAI client retries before caller fallback.
- AH-22: Worker cleanup best effort.
- AH-23: Response cache miss fallback.
- AH-24: Admin proxy/client sanitization.
- AH-25: Frontend localStorage preference suppression.
- AH-28: Honeypot silent success.
- AH-31: Webhook attempt-record best effort after handler success.
- AH-33: INFO log default in production.
- AH-34: Scraper log redaction for flat sensitive fields.

### Acceptable But Should Be Documented

- AH-02: `/healthz` can stay healthy with Redis component error.
- AH-08: OpenTelemetry disabled when endpoint unset.
- AH-20: Provider request `None` contract for backoff/timeout.
- AH-27: SSE construction failure means no live updates.
- AH-30: Realtime event drop behavior before production enablement.

### Acceptable But Needs Better Telemetry

- AH-07: Rate-limit Redis fallback to per-replica memory.
- AH-09: Metrics package ImportError no-op.
- AH-12: Club claim notification failure.
- AH-16: Redis lock skipped polling.
- AH-18: Repeated missing external IDs.
- AH-19: Boxscore soft failures.
- AH-21: Unexpected missing job runs.
- AH-26: Frontend runtime/fetch errors.
- AH-17: Degraded polling jobs should get metrics/alerting.

### Should Be Tightened Before Prod

- AH-32: Unknown env var ignore without deploy lint.

### High Risk / Hidden Failure

- AH-06: Admin role origin/referrer fallback needs route-level proof tests.

### Security-Sensitive Suppression

- AH-06: Admin role origin/referrer fallback.
- AH-10: Audit write failures do not block success.
- AH-24: Proxy sanitization is positive, but server logs include internal target details.
- AH-28: Honeypot silence is intentionally security-positive.

### Data Loss / Corruption Risk

- AH-17: Partial ingestion may leave stale/missing game data.
- AH-18: Missing external IDs can prevent active-game updates.
- AH-19: Boxscore DB soft failure can suppress incomplete updates.

### Observability Blind Spots

- AH-08: No OTLP endpoint.
- AH-09: Metrics no-op on missing package.
- AH-10: Audit write failure has no retry/dead-letter.
- AH-16: Lock skipped polling not prominent enough.
- AH-17: Degraded polling jobs need alerting.
- AH-26: Frontend failures browser-local only.
- AH-33: Debug-only breadcrumbs hidden in prod.

## Section 5: Environment Review

### Where Prod Is Quieter Than Non-Prod

- API and scraper logging default to INFO in production and DEBUG otherwise.
- Missing OpenTelemetry package is debug-only in pipeline metrics.
- Missing external IDs in polling helpers are sometimes debug-only.
- Frontend console warnings/errors are not centrally collected by default.

### Where Prod Is More Permissive Than Non-Prod

Prod is not broadly more permissive for auth or configuration. Important examples fail stricter in prod/staging:

- Missing `API_KEY` / `CONSUMER_API_KEY` is rejected in prod/staging.
- `AUTH_ENABLED=false` is rejected in prod/staging.
- Weak JWT/API key settings are rejected in prod/staging.
- OpenAPI docs are disabled in prod/staging.

The main permissive production behavior is operational fail-soft handling, not auth bypass: Redis rate-limit fallback, cache fallback, health component downgrade, best-effort audit writes, and optional frontend/realtime degradation.

### Where Prod May Fail Open

- AH-07: global rate limiting weakens to local memory buckets.
- AH-10: audit write failure does not affect protected operation success.

### Where Prod May Hide Actionable Errors

- AH-18/AH-19: missing IDs and helper-level soft failures can still hide stale data unless metrics are monitored.
- AH-09: missing metrics instrumentation can disappear at DEBUG.
- AH-26/AH-27: frontend degradation may not reach server-side operations.
- AH-32: unknown env vars can hide typoed config.

### Reasonableness

Most environment differences are reasonable. The remaining risky cases are not caused by dev/prod switches directly; they are caused by availability-oriented fallbacks in production paths that need stronger metrics and alerting for ingestion completeness, audit durability, and config mistakes.

## Section 6: Recommended Remediation Plan

### Quick Wins

1. Add a metric and alert for `RATE_LIMIT_USE_REDIS` fallback activation.
2. Promote missing external IDs for active games from debug/no-op to warning after a short threshold.
3. Add browser telemetry or a lightweight admin UI error event for ErrorBoundary and key fetch failures.
4. Add a deploy-time check for unknown env vars instead of changing runtime config parsing.
5. Add alerts for degraded polling jobs and task-hold Redis read failures.

### Medium Effort Cleanup

1. Promote repeated missing external IDs to metrics and warning-level summaries.
2. Add explicit per-league degraded polling metrics from job-run `summary_data`.
3. Add an explicit "live updates disconnected" state for SSE consumers where stale data matters.
4. Classify audit events into best-effort notes versus durable security events.
5. Add recursive redaction if scraper logs start carrying nested provider payloads.

### High Value Hardening

1. Add route-level security tests proving admin-only endpoints cannot be reached via origin/referrer manipulation without the intended API-key/JWT dependency path.
2. Add ingestion SLO metrics: active games missing provider IDs, per-poll failed games, provider backoff state, and degraded job counts.
3. Make critical audit events durable before API success or retry them through a queue.

### Documentation Gaps

1. Document `/healthz` versus `/ready` semantics.
2. Document the provider request wrapper `None` contract.
3. Document task hold behavior, including Redis-unavailable fail-closed semantics.
4. Document best-effort audit limitations or change audit implementation for critical events.
5. Document which realtime paths are mounted and which remain non-authoritative.

### Test Gaps

1. Test prod/staging rejection for auth-disabled and missing key settings.
2. Test admin role derivation cannot elevate outside intended admin dependency wiring.
3. Test polling degraded status on suppressed per-game errors.
4. Test rate-limit Redis fallback emits the expected metric/log.
5. Test circuit status returns degraded/unknown when Redis state is unreadable.

### Telemetry / Alerting Gaps

1. Alert on Redis rate-limit fallback.
2. Alert on task-hold Redis read failure.
3. Track degraded polling jobs separately from successful jobs.
4. Track audit write failures.
5. Track missing OpenTelemetry exporter/package in production if telemetry is required.

## Appendix A: Warning, Lint, and Security Suppressions

- `api/pyproject.toml` filters an AsyncMock RuntimeWarning in tests only. This is not a production suppression.
- `api/pyproject.toml` omits several hard-to-integration-test areas from coverage thresholds. This is a test coverage policy risk, not runtime error handling.
- `api/app/analytics/models/core/model_loader.py` suppresses Bandit/pickle warnings on `_load_pickle()` after HMAC signature verification and symlink/traversal checks. The suppression is acceptable if model artifact signing keys and artifact storage remain protected.
- Type ignores and `noqa` entries in schema/model-registration areas are mostly static-analysis accommodation, not runtime suppression. No production behavior risk was found from those comments alone.

## Appendix B: Lower-Priority Non-Active or Legacy Areas

The scan found many broad exception handlers in analytics, golf/fairbet live odds, social collectors, and realtime modules. Several of these routes/tasks are not mounted or scheduled in the current catch-up-centered runtime, so they are lower production priority. They should still follow the same standard before being promoted:

- handlers that continue after partial work should emit degraded status or metrics;
- Redis/status-store failures should return `unknown` rather than healthy defaults;
- retry queues should have visible dead-letter metrics;
- optional UI/realtime features should expose stale/disconnected state.

## Direct Verdict

**Prod posture has notable risk areas.**

The system has many well-designed resilience boundaries, and most suppressions are acceptable notes or low-risk fallbacks. The posture is not fully "notes only" because scheduled ingestion and operator guardrails can currently turn real failures into apparent success or continued execution. Tightening task hold behavior, degraded polling status, admin role proof tests, audit durability, and status-store observability would move the posture toward acceptable production-grade suppression.
