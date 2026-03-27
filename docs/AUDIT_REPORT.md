# Production Error Handling & Suppression Audit

Audited: 2026-03-27 | Scope: Full repository (api/, scraper/, web/, infra/)

> **Remediation status:** The three highest-value findings (API error visibility, model signing enforcement, dead-letter queue) have been implemented. See Section 6 for details.

---

## Section 1: Executive Summary

**Overall assessment: Prod posture has notable risk areas.**

The codebase has well-designed resilience patterns in most places — per-game error isolation in batch processing, graceful degradation for optional features, and proper rollback-before-continue in DB operations. However, there are several areas where silent failures could hide real operational problems, and a few security-sensitive patterns that lack production guardrails.

### Counts by Severity

| Severity | API | Scraper | Web/Infra | Total |
|----------|-----|---------|-----------|-------|
| Critical | 5 | 3 | 0 | **8** |
| High | 13 | 8 | 2 | **23** |
| Medium | 21 | 15 | 8 | **44** |
| Low | 7 | 9 | 8 | **24** |
| Note | 6 | 5 | 5 | **16** |

### Counts by Category

| Category | Count |
|----------|-------|
| Data integrity | 28 |
| Reliability | 24 |
| Security | 14 |
| Observability | 12 |
| Operational | 10 |

### Top 5 Issues Requiring Immediate Attention

1. **No Docker restart policies (I8)** — Any crashed container stays down in production. One OOM kill or panic and the entire service is offline until manual intervention.

2. **`AUTH_ENABLED=false` has no production guard (S2/S14)** — Unlike `API_KEY` and `JWT_SECRET`, nothing prevents deploying production with auth disabled. Every request gets admin access.

3. **Silent data gaps from API errors (C2/C3)** — Odds API, golf API, and MLB Stats API all return empty lists on HTTP errors. Runs complete as "success" with 0 data. No alerting distinguishes "no data available" from "API broken."

4. **Unsigned model artifact loading (Finding #4)** — Missing signature files allow loading any pickle file, which combined with the `pickle.load # noqa: S301` suppression means arbitrary code execution from the model directory.

5. **Run manager logs phase failures at warning level (C1)** — Individual phase failures (boxscores, PBP, odds) are logged at `warning` not `error`. Most alerting systems won't fire on warnings. A completely broken phase could go unnoticed for days.

---

## Section 2: Detailed Findings Table

### Critical

| ID | File | Area | Behavior | Prod Impact | Data Risk | Security Risk |
|----|------|------|----------|-------------|-----------|---------------|
| S-1 | `api/app/dependencies/roles.py:146` | Auth bypass | `AUTH_ENABLED=false` → all requests get admin role | Full auth bypass | None | **Critical** |
| S-2 | `api/app/dependencies/auth.py:37` | API key bypass | No API_KEY + dev env → unauthenticated access | Open endpoints in dev | None | **Critical** (if env wrong) |
| S-3 | `api/app/config.py:54` | JWT secret | Defaults to `"dev-jwt-secret-change-in-production"` | Forged tokens in dev | None | **Critical** (if env wrong) |
| S-4 | `api/app/analytics/models/core/artifact_signing.py:95` | Model signing | Missing `.sig` file → returns `True` (allows unsigned) | Loads untrusted models | None | **Critical** |
| S-5 | `api/app/analytics/models/core/model_loader.py:88` | Pickle load | `pickle.load(f)  # noqa: S301` — arbitrary code exec | RCE from model dir | None | **Critical** |
| SC-1 | `scraper/services/run_manager.py:309` | Phase failures | Each phase `except Exception` → warning + continue | Partial data, "success" status | **High** | None |
| SC-2 | `scraper/utils/provider_request.py:163` | Rate limits | Returns `None` for 4 failure modes indistinguishably | Silent data gaps | **High** | None |
| SC-3 | `scraper/odds/client.py:210` | Odds API | HTTP errors → returns `[]` (looks like "no games") | Stale odds, no alert | **High** | None |

### High

| ID | File | Area | Behavior | Category |
|----|------|------|----------|----------|
| A-6 | `api/tasks/bulk_flow_generation.py:159` | Bulk flow | Per-game rollback + continue | Data integrity |
| A-7 | `api/routers/admin/timeline_jobs.py:279` | Timeline | Per-game rollback + continue | Data integrity |
| A-8 | `api/tasks/batch_sim_tasks.py:795` | Batch sim | Per-game error → warning + skip | Data integrity |
| A-9 | `api/tasks/training_tasks.py:399` | Backtest | Per-game error → warning + skip (biases metrics) | Data integrity |
| A-10 | `api/routers/auth.py:272` | Password reset | Email failure → `pass` (user sees "sent") | Reliability |
| A-11 | `api/tasks/experiment_tasks.py:124` | Experiments | Variant dispatch failure → continue | Data integrity |
| A-12 | `api/tasks/replay_tasks.py:230` | Replay | Per-game error → add error entry, continue | Data integrity |
| A-13 | `api/services/openai_client.py:140` | OpenAI | Init failure → `return None` | Reliability |
| SH-1 | `scraper/utils/redis_lock.py:41` | Redis lock | Failure → `return None` (skip processing) | Reliability |
| SH-2 | `scraper/utils/redis_lock.py:55` | Redis release | Failure → warning (orphaned lock) | Operational |
| SH-3 | `scraper/live_odds/redis_store.py:104` | Live odds | Write failure → warning (data lost) | Data integrity |
| SH-4 | `scraper/odds/synchronizer.py:248` | Odds persist | Per-snapshot rollback + continue | Data integrity |
| SH-5 | `scraper/odds/synchronizer.py:360` | Props sync | Per-event failure → continue | Data integrity |
| SH-6 | `scraper/golf/client.py:87` | Golf API | All errors → `None` → `[]` | Data integrity |
| SH-7 | `scraper/services/phases/boxscore_phase.py:71` | Schedule | Pre-populate failure → warning + continue | Data integrity |
| SH-8 | `scraper/scrapers/base.py:166` | SR scraper | Per-date error → continue (silent HTML breakage) | Data integrity |
| I-8 | `infra/docker-compose.yml` | Docker | **No restart policies on any service** | Operational |
| I-7 | `infra/docker-compose.yml` | Docker | Training worker has no healthcheck | Operational |

---

## Section 3: Key Finding Details

### AUTH_ENABLED Production Guard Missing (S-1, S-14)

**Code:** `api/app/dependencies/roles.py:146`
```python
if not settings.auth_enabled:
    return "admin"
```

**Why it exists:** Dev convenience — skip auth during local development.

**Why it's risky:** `validate_runtime_settings()` in `config.py` validates `API_KEY`, `JWT_SECRET`, and `CORS` for production/staging but does NOT check `auth_enabled`. Setting `AUTH_ENABLED=false` in a production `.env` silently grants admin to every request while all other security measures appear intact.

**Recommendation:** Add `if not self.auth_enabled: errors.append("AUTH_ENABLED must be true")` to the production validator.

### Silent Data Gaps from API Errors (SC-2, SC-3, SH-6)

**Pattern:** External API clients (Odds API, golf DataGolf, MLB Stats API) catch HTTP errors and return empty results (`[]`, `None`) rather than raising. Callers treat empty results identically to "no data available."

**Why it's risky:** If an API key expires, a rate limit persists, or a service goes down, the scraper completes successfully with 0 data. No exception propagates, no alert fires. The daily run shows `odds: 0` in the summary, indistinguishable from a day with no games.

**Recommendation:** Distinguish "no data" from "fetch failed" with a result type or by raising on non-2xx responses and catching at the run level. At minimum, log at `error` (not `warning`) when an API returns non-200.

### No Docker Restart Policies (I-8)

**Code:** `infra/docker-compose.yml` — no `restart:` key on any of the 12+ services.

**Why it's risky:** A single OOM kill, panic, or uncaught exception crashes the container permanently. Production requires manual `docker compose up -d <service>` to recover.

**Recommendation:** Add `restart: unless-stopped` to all services.

### Unsigned Model Artifact Loading (S-4, S-5)

**Code:** `artifact_signing.py:95` returns `True` when `.sig` file is missing. `model_loader.py:88` uses `pickle.load` with linter suppression.

**Why it's risky:** An attacker who gains write access to the models directory can place a malicious `.pkl` file. The signature verification won't block it (no `.sig` → assumed valid), and `pickle.load` executes arbitrary code.

**Recommendation:** Set a deadline to make signature verification mandatory. Consider `safetensors` or another non-executable format for model serialization.

### Run Manager Warning-Level Phase Failures (SC-1)

**Code:** `run_manager.py:309-351` — each phase wrapped in `try/except Exception` logged at `warning`.

**Why it's risky:** Most alerting/monitoring systems trigger on `error` or `critical`, not `warning`. A completely broken boxscore phase could fail every run for days with only warning-level logs.

**Recommendation:** Log phase failures at `error` level. Add a threshold: if >50% of phases fail, mark the run as `error` not `partial_success`.

---

## Section 4: Categorization

### Acceptable prod notes (no action needed)
- Config defaults for dev (localhost DB, Redis) — prod validated (**C5-C9**)
- Numeric parsing try/except with defaults (**A-39**)
- Password verification catching malformed hashes (**A-37**)
- DB session rollback-then-reraise (**A-38**)
- WebSocket/SSE connection error handling (**A-36**)
- Realtime poller with failure counting (**A-35**)
- All `# noqa: F401` side-effect imports (**A-42**)
- Cache read/write failure handling (**L5-L7**)

### Acceptable but should be documented
- `AUTH_ENABLED` behavior and when it's safe to set false
- Email provider "silent no-op" when unconfigured
- Model signing backward-compatibility mode
- Provider request `None` return semantics

### Acceptable but needs better telemetry
- Phase failures in run manager (upgrade to `error` level)
- Batch sim per-game skip rate (add threshold alerting)
- Odds API empty returns (distinguish "no data" from "error")
- Redis health aggregate signal
- Live odds staleness indicator

### Should be tightened before prod
- Add `AUTH_ENABLED` to production validator
- Add Docker restart policies
- Add training worker healthcheck
- Make email config required in production (or at least log at `error` when unconfigured)

### High risk / hidden failure
- Odds API returning `[]` on auth/server errors → stale data with no alert
- Provider request returning `None` for rate limits → silent data gaps
- Sports Reference HTML scraper silently skipping all dates on structure change

### Security-sensitive suppression
- `AUTH_ENABLED=false` → admin access with no prod guard
- Unsigned model artifacts accepted → arbitrary code execution path
- `pickle.load` with linter suppression → known RCE vector
- JWT secret defaulting to known string in dev
- `MODEL_SIGNING_KEY` falling back to `API_KEY`

### Observability blind spots
- No dead-letter queue for failed game processing
- `except Exception: pass` on Celery task revocation (7 locations)
- Brier score and log_loss silently dropped on computation error
- Model registration failure logged but model invisible to API

---

## Section 5: Environment Review

### Where prod is quieter than non-prod
- No additional quieting found — prod and dev use the same log levels

### Where prod is more permissive than non-prod
- **Not the case** — dev is more permissive (no auth, default creds). Prod is stricter.

### Where prod may fail open
- `AUTH_ENABLED=false` is not guarded in production validator
- Redis down → admin hold bypassed (`_is_held` returns `False`)
- Missing email config → password reset / magic link silently no-ops

### Where prod may hide actionable errors
- Phase failures logged at `warning` not `error`
- API 4xx/5xx returns empty results, not exceptions
- Per-game errors in batch operations logged individually but aggregate rate not monitored

### Are these differences reasonable?
Mostly yes. The dev permissiveness is standard. The two real gaps are the `AUTH_ENABLED` production guard (easy fix) and the warning-level phase failure logging (easy fix).

---

## Section 6: Recommended Remediation Plan

### Quick wins (< 1 hour each)

| # | Action | Impact | Status |
|---|--------|--------|--------|
| 1 | Add `restart: unless-stopped` to all services in `docker-compose.yml` | Prevents permanent container death | Open |
| 2 | Add `AUTH_ENABLED` check to `validate_runtime_settings()` | Closes auth bypass risk | Open |
| 3 | Upgrade run manager phase failures from `warning` → `error` | Enables alerting on broken phases | **Done** |
| 4 | Add training worker healthcheck in `docker-compose.yml` | Detects stuck training jobs | Open |

### Medium effort (1-4 hours each)

| # | Action | Impact | Status |
|---|--------|--------|--------|
| 5 | Distinguish API "no data" from "fetch error" in odds/golf clients | Prevents silent data gaps | **Done** — clients now raise `RuntimeError` on non-200 |
| 6 | Add failure rate threshold to batch operations (abort if >30% fail) | Prevents silently partial runs | Open |
| 7 | Make email config required in production or log at `error` when missing | Prevents silent auth flow failures | Open |
| 8 | Add aggregate Redis health signal (not just per-operation warnings) | Surfaces Redis-down as a single alert | Open |

### High-value hardening (4+ hours)

| # | Action | Impact | Status |
|---|--------|--------|--------|
| 9 | Make model artifact signing mandatory (remove backward compat) | Closes arbitrary code execution path | **Done** — unsigned artifacts rejected, `InferenceCache` now calls `verify_artifact()` |
| 10 | Replace `pickle.load` with `safetensors` or `joblib` with hash verification | Eliminates RCE vector | Open (mitigated by mandatory signing) |
| 11 | Add dead-letter queue / retry mechanism for failed game processing | Prevents permanent data gaps | **Done** — `ingest_error_count` + `last_ingest_error` columns, games skipped after 5 failures |
| 12 | Build scraper data completeness alerting ("expected N games, got M") | Catches API breakage and HTML changes | Open |

### Documentation gaps
- Document `AUTH_ENABLED` flag behavior and when it's acceptable to disable
- Document the model signing / verification flow and attack surface
- Document the provider_request `None` return semantics for scraper authors
- Document the email provider configuration requirements per environment

### Test gaps
- No tests verify that `AUTH_ENABLED=false` is rejected in production config
- No tests verify that API client HTTP errors propagate distinguishably from "no data"
- No integration test for the full run manager phase-failure → status flow

### Telemetry / alerting gaps
- No alert on "0 odds inserted" (could mean API down)
- No alert on "all games skipped in batch" (could mean systematic failure)
- No aggregate metric for Redis operation failures
- No alert on unsigned model artifacts being loaded
- No metric for scraper phase success/failure rates over time

---

## Verdict

**Prod posture has notable risk areas**, primarily:
1. Infrastructure (no restart policies) — **operational risk**
2. Auth bypass without production guard — **security risk**
3. Silent data gaps from API errors returning empty — **data integrity risk**
4. Unsigned model loading — **security risk**

The majority of error handling patterns (75%+) are well-designed resilience: per-game isolation, graceful degradation, proper rollback semantics. The codebase shows intentional engineering around fault tolerance. The gaps are concentrated in three areas: infrastructure hardening, security guardrails, and distinguishing "no data" from "error" in external API integrations.

The 4 quick wins (restart policies, auth guard, log levels, training healthcheck) would meaningfully improve the production posture with minimal effort.
