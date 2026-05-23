# Security Review Report

Audit date: 2026-05-23

Scope: Sports Data Admin API, Next.js web app, scraper workers, Docker/Caddy
deployment files, and repo-local documentation/configuration.

This report is evidence-based. Findings below cite code paths that were present
in the repository at review time. Dependency CVEs were not asserted unless
verified by local tooling.

## A. Repository Understanding Summary

Sports Data Admin is a catch-up-centered sports data and admin service. The
active runtime is:

- FastAPI backend in `api/main.py`
- Next.js admin/browser surface in `web/src/app`
- Celery scraper/beat workers under `scraper/sports_scraper`
- PostgreSQL and Redis behind Docker Compose
- Caddy as the intended public edge in `infra/Caddyfile`
- Optional observability services under the `observability` profile

### Active API Surface

`api/main.py` currently mounts:

- `/api/v1/*` through `app.routers.v1`, protected by consumer API key
- `/api/sports/*`, `/api/social/*`, and `/api/admin/*`, protected by admin API key
- `/metrics`, `/health`, `/healthz`, and `/ready` without API-key auth

Several routers exist but are not mounted in the active app, including auth,
onboarding, webhooks, commerce, clubs, golf, FairBet, analytics, and realtime
WebSocket/SSE router paths. Those modules still matter for future security
because tests import them and Caddy previously reserved some matching paths.

### Frontend Surface

The browser uses `/proxy` as its API base. The proxy route in
`web/src/app/proxy/[...path]/route.ts` forwards requests to the API and injects
`SPORTS_API_KEY` server-side. This keeps the key out of the browser bundle, but
it means the web tier becomes a privilege boundary. If the web tier is public
without authentication, `/proxy` can expose API-key-backed backend actions.

### Trust Boundaries

Key boundaries:

- Public internet to Caddy
- Caddy to Next.js and FastAPI over localhost
- Browser to Next.js `/proxy`
- Next.js server to FastAPI with injected API key
- FastAPI to PostgreSQL and Redis
- Celery workers to database, Redis, and external sports data sources
- Admin API to log-relay sidecar
- Log-relay sidecar to Docker socket
- Optional Grafana/Prometheus/OTel surfaces

### Security Assumptions Found

- Production and staging require strong API/JWT settings through
  `api/app/config.py`.
- API docs are disabled in production/staging by `api/main.py`.
- Admin API routes rely on `X-API-Key`, not a browser session.
- The web admin surface is expected to be gated by `ADMIN_PASSWORD`, but the
  repository had no Next proxy gate or Caddy basic auth enforcing it before this
  pass.
- `/metrics` and health endpoints are intended operational surfaces, not public
  app features.

## B. Findings Table

| ID | Title | Category | Severity | Confidence | Status |
| --- | --- | --- | --- | --- | --- |
| S1 | Public web proxy could inject admin API key without an auth gate | Auth / API boundary | Critical | High | Fixed in this pass |
| S2 | Compose exposed API, web, and observability ports on all interfaces | Deployment / network exposure | High | High | Fixed in this pass |
| S3 | Admin role can be inferred from Origin/Referer if reused on unauthenticated routes | Authorization | High | Medium | Needs backend hardening |
| S4 | Admin password default reused database password and was not enforced | Secrets / config | High | High | Partially fixed |
| S5 | Unauthenticated `/metrics` can expose operational data if API is reachable directly | Observability | Medium | High | Mitigated by port binding; add auth/allowlist later |
| S6 | Spoiler-policy payloads need fail-closed leak checks | Data exposure | Medium | High | Fixed before this report; documented here |
| S7 | Admin log endpoint can expose sensitive runtime logs | Data exposure / operations | Medium | High | Accept with tighter redaction backlog |
| S8 | Caddy routed `/docs` and `/openapi.json` despite prod disabling docs | Hardening | Low | High | Fixed in this pass |
| S9 | CSP still allows inline scripts/styles | Browser hardening | Low | High | Accept short-term; nonce roadmap |
| S10 | Model artifact loading uses pickle/joblib in some analytics paths | Supply chain / deserialization | Low | Medium | Accept where signed; verify legacy paths before mounting analytics |
| S11 | Local untracked env files contain real secrets | Secrets hygiene | Low | Medium | Accept locally; add scanning/rotation controls |
| S12 | SQL injection risk appears low in mounted routes | Positive control | Informational | High | No action |
| S13 | Stripe webhook module verifies signatures and is not mounted | Positive control | Informational | High | No action until mounted |
| S14 | Repo dependency audits found no known vulnerabilities in production sets | Supply chain | Informational | High | No action; keep CI gate |

## C. Detailed Findings

### S1: Public Web Proxy Could Inject Admin API Key Without an Auth Gate

Category: Auth / API boundary

Severity: Critical

Confidence: High

Affected area:

- `web/src/app/proxy/[...path]/route.ts`
- `web/src/lib/api/apiBase.ts`
- `infra/Caddyfile`
- `infra/docker-compose.yml`
- `api/main.py`

Evidence:

- The browser API base is `/proxy`.
- The Next proxy injects `SPORTS_API_KEY` as `X-API-Key`.
- Caddy routes all non-API paths to Next.js.
- No `web/src/proxy.ts` auth gate existed and no Caddy `basic_auth` block existed.
- `ADMIN_PASSWORD` was present in compose but unused by code.

Why it matters:

If the deployed web app is reachable by an unauthenticated user, a caller could
hit privileged `/proxy/api/admin/*`, `/proxy/api/sports/*`, or similar paths and
let the Next server attach the API key. That collapses the intended API-key
boundary.

Realistic exploit scenario:

An unauthenticated internet user requests
`/proxy/api/admin/sports/logs?container=sports-api&lines=1000`. The browser does
not know the API key, but the server-side proxy adds it. Before this pass, no web
auth gate blocked the request.

Recommended fix:

Require authentication at the web edge for admin UI and privileged proxy paths.
Also strip Basic authorization before forwarding to FastAPI.

Disposition:

Fixed in this pass with `web/src/proxy.ts` and a proxy-route header cleanup.

### S2: Compose Exposed API, Web, and Observability Ports on All Interfaces

Category: Deployment / network exposure

Severity: High

Confidence: High

Affected area:

- `infra/docker-compose.yml`

Evidence:

The API, web, OTel, Grafana, and Prometheus services used host port mappings
without an explicit `127.0.0.1` bind.

Why it matters:

Caddy is the intended public edge. Binding service ports to all interfaces can
expose direct API, admin UI, metrics, Grafana, Prometheus, or OTel collector
surfaces depending on host firewall posture.

Realistic exploit scenario:

If a host firewall allows inbound traffic to port 8000, callers can bypass Caddy
and reach FastAPI directly, including unauthenticated health and metrics routes.

Recommended fix:

Bind host ports to `127.0.0.1` unless the service is intentionally public.

Disposition:

Fixed in this pass for API, web, OTel collector, Grafana, and Prometheus.

### S3: Admin Role Can Be Inferred From Origin/Referer

Category: Authorization

Severity: High

Confidence: Medium

Affected area:

- `api/app/dependencies/roles.py`

Evidence:

`resolve_role()` returns `admin` when no bearer token exists and the request
origin context matches `ADMIN_ORIGINS`. This check can consider `Origin`,
trusted `X-Forwarded-Origin`, and `Referer`.

Why it matters:

Origin and Referer are request metadata, not credentials. This is acceptable
only when the dependency is used behind a stronger route-level auth dependency.
If `require_admin()` is reused on an unauthenticated mounted route, a forged
Origin/Referer could become an auth bypass.

Realistic exploit scenario:

A future router is mounted with `require_admin` but without API-key dependency.
An attacker sends a request with an allowed `Origin` header and receives admin
role.

Recommended fix:

Remove origin/referrer-derived admin authority or only allow it when
`request.state.api_key_verified` is already true. Add tests that prove
`ADMIN_ORIGINS` alone cannot satisfy `require_admin`.

Disposition:

Needs backend hardening. Not changed in this pass because it may affect dormant
JWT/auth routes and requires route ownership review.

### S4: Admin Password Default Reused Database Password and Was Not Enforced

Category: Secrets / config

Severity: High

Confidence: High

Affected area:

- `infra/docker-compose.yml`
- `web/src/proxy.ts`

Evidence:

Compose previously set `ADMIN_PASSWORD` from `${POSTGRES_PASSWORD:-}` and the
comment stated it used the same password as Postgres. Grafana also reused the
Postgres password by default. No code consumed `ADMIN_PASSWORD`.

Why it matters:

Credential reuse increases blast radius. The absence of enforcement also made
the env var misleading: operators could believe web admin was protected when it
was not.

Realistic exploit scenario:

An operator sets a database password expecting it to protect both DB and admin.
The web app remains unauthenticated, or a leaked DB password also unlocks web
admin.

Recommended fix:

Use independent `ADMIN_PASSWORD`. Fail closed in production/staging when it is
missing for protected paths.

Disposition:

Partially fixed in this pass. The Next proxy gate enforces the password, compose now
reads `${ADMIN_PASSWORD:-}`, and Grafana reads `GF_SECURITY_ADMIN_PASSWORD`
instead of the database password. Follow-up should add production deployment
validation so missing `ADMIN_PASSWORD` fails before startup.

### S5: Unauthenticated `/metrics` Can Expose Operational Data

Category: Observability

Severity: Medium

Confidence: High

Affected area:

- `api/main.py`
- `infra/docker-compose.yml`
- `infra/Caddyfile`

Evidence:

`/metrics` is mounted without API-key auth. Caddy does not explicitly publish
`/metrics`, but direct API port exposure made it reachable if port 8000 was
public.

Why it matters:

Metrics can leak service names, route names, traffic patterns, and operational
state. That is usually acceptable to Prometheus, not to the public internet.

Realistic exploit scenario:

A scanner discovers `:8000/metrics` on the host and collects operational
metadata.

Recommended fix:

Keep port 8000 localhost-only and consider an explicit metrics allowlist or
separate internal listener.

Disposition:

Mitigated in this pass by localhost port binding. Auth/allowlist remains a
medium-term hardening item.

### S6: Spoiler-Policy Payloads Need Fail-Closed Leak Checks

Category: Data exposure

Severity: Medium

Confidence: High

Affected area:

- `api/app/scroll_down_mlb/router.py`

Evidence:

The daily pressure pack response emits `card_payload` as `dict[str, Any]`, so
the stricter typed deck response contract cannot alone prevent final-score
leaks. The code now validates `validate_no_final_score_leak()` before returning
the pack and fails closed with 500 if a leak is detected.

Why it matters:

This app intentionally protects catch-up users from spoilers. A final score in
pre-reveal payloads is a product data exposure issue.

Realistic exploit scenario:

A future ingestion bug persists a leaking payload under the pre-reveal policy.
Without the fail-closed guard, the API serves the leak.

Recommended fix:

Keep the fail-closed guard and add regression tests for every response surface
that emits flexible payload dictionaries.

Disposition:

Fixed before this report and treated as a positive security control.

### S7: Admin Log Endpoint Can Expose Sensitive Runtime Logs

Category: Data exposure / operations

Severity: Medium

Confidence: High

Affected area:

- `api/app/routers/sports/docker_logs.py`
- `infra/log-relay/server.py`
- `infra/docker-compose.yml`

Evidence:

The admin API fetches logs from a sidecar. The sidecar mounts Docker socket
read-only and has a container allowlist. The API and sidecar allowlists are not
identical, and logs are returned to the admin browser.

Why it matters:

Logs can contain secrets, webhook payloads, account identifiers, or operational
errors. The sidecar design is safer than mounting Docker socket into the API,
but the returned log text is still sensitive.

Realistic exploit scenario:

If admin/proxy auth is bypassed, an attacker can request recent logs and search
for tokens or private data.

Recommended fix:

Keep the sidecar isolated. Align API and sidecar allowlists, add response
redaction for known secret patterns, cap default line counts lower, and audit
log access events.

Disposition:

Acceptable for admin-only access after S1 fix, but should be hardened.

### S8: Caddy Routed Docs/OpenAPI Despite Prod Disabling Docs

Category: Hardening

Severity: Low

Confidence: High

Affected area:

- `infra/Caddyfile`
- `api/main.py`

Evidence:

Caddy had explicit `/docs` and `/openapi.json` routes. FastAPI disables docs in
production/staging, but the edge config still reserved those paths.

Why it matters:

Redundant doc routes increase chance of accidental exposure if the API runs with
development settings behind the production Caddyfile.

Recommended fix:

Remove explicit docs/OpenAPI Caddy routes unless intentionally exposing them.

Disposition:

Fixed in this pass.

### S9: CSP Still Allows Inline Scripts/Styles

Category: Browser hardening

Severity: Low

Confidence: High

Affected area:

- `web/next.config.ts`
- `infra/Caddyfile`

Evidence:

Both Next and Caddy CSPs include `'unsafe-inline'` for script/style handling.
Comments explain Next.js and Twitter embed constraints.

Why it matters:

Inline script allowance weakens XSS containment if an injection bug appears.
The repo does not show `dangerouslySetInnerHTML`, which reduces current risk.

Recommended fix:

Move toward nonce or hash-based CSP when Next middleware/header wiring is ready.
Keep Twitter permissions as narrow as possible.

Disposition:

Accept short-term. Track as browser-hardening roadmap.

### S10: Model Artifact Loading Uses Pickle/Joblib in Some Analytics Paths

Category: Supply chain / deserialization

Severity: Low

Confidence: Medium

Affected area:

- `api/app/analytics/models/core/model_loader.py`
- `api/app/analytics/inference/inference_cache.py`
- `api/app/analytics/api/_simulation_helpers.py`
- `api/app/tasks/training_tasks.py`

Evidence:

The core model loader verifies HMAC signatures and root containment before
loading joblib/pickle artifacts. Some other analytics paths call `joblib.load()`
directly. Analytics routers are not mounted by the active app.

Why it matters:

Pickle/joblib are unsafe for untrusted inputs. The signed loader is a good
pattern, but direct loads should be verified before analytics routes are mounted
in production.

Recommended fix:

Route all model loads through the signed loader or document each trusted local
artifact source. Add a static check preventing new direct `joblib.load()` calls
outside approved modules.

Disposition:

Accept while analytics remains unmounted; investigate before enabling analytics
routes.

### S11: Local Untracked Env Files Contain Real Secrets

Category: Secrets hygiene

Severity: Low

Confidence: Medium

Affected area:

- `infra/.env`
- `web/.env.local`
- `.gitignore`

Evidence:

Local env files are present and untracked. This is normal for development, but
it means the repo depends on Git ignore discipline and secret scanning to avoid
accidental commits.

Why it matters:

Local secret files are a common source of accidental leaks.

Recommended fix:

Keep env files ignored, run secret scanning in CI and pre-commit, and rotate any
secret that is accidentally printed or committed.

Disposition:

Accept locally; add automated scanning.

### S12: SQL Injection Risk Appears Low in Mounted Routes

Category: Positive control

Severity: Informational

Confidence: High

Evidence:

Mounted API routes use SQLAlchemy query builders and Pydantic models for request
data. No mounted route review found raw user input being interpolated into SQL.

Disposition:

No immediate action.

### S13: Stripe Webhook Module Verifies Signatures and Is Not Mounted

Category: Positive control

Severity: Informational

Confidence: High

Evidence:

Webhook tests exercise Stripe signature verification and idempotency. The active
FastAPI app does not mount the webhook router.

Disposition:

No immediate action. If mounted later, keep signature verification mandatory and
document the edge route.

### S14: Repo Dependency Audits Found No Known Vulnerabilities in Production Sets

Category: Supply chain

Severity: Informational

Confidence: High

Evidence:

- `pnpm --dir web audit --prod --audit-level high` returned no known
  vulnerabilities.
- `python -m pip_audit -r api/requirements.txt` returned no known
  vulnerabilities.
- `uv export --project scraper --no-dev --no-emit-project --no-emit-workspace
  --no-emit-local --no-hashes --format requirements.txt` followed by
  `python -m pip_audit -r /tmp/sda-scraper-req.txt` returned no known
  vulnerabilities.

Notes:

A direct `python -m pip_audit` against the shell environment audited the global
Anaconda interpreter rather than this repository, so that output is not treated
as repo evidence.

Disposition:

No immediate dependency fix. Add the same audits as CI gates so this remains
true over time.

## D. Safe Hardening Changes Implemented

Implemented in this pass:

- Added `web/src/proxy.ts` to require Basic auth for `/admin` and
  privileged `/proxy` paths in production/staging, and whenever
  `ADMIN_PASSWORD` is configured.
- The Next proxy gate fails closed with 503 for protected paths in production/staging
  when `ADMIN_PASSWORD` is missing.
- Added `web/src/proxy.test.ts` coverage for protected admin/proxy paths,
  matching credentials, production fail-closed behavior, and dev bypass.
- Updated the Next proxy to strip browser Basic auth before forwarding to
  FastAPI, while preserving non-Basic authorization headers.
- Bound API, web, OTel, Grafana, and Prometheus host ports to `127.0.0.1` in
  `infra/docker-compose.yml`.
- Changed web `ADMIN_PASSWORD` compose wiring to use an independent
  `ADMIN_PASSWORD`, not `POSTGRES_PASSWORD`.
- Changed Grafana compose wiring to use `GF_SECURITY_ADMIN_PASSWORD`, not
  `POSTGRES_PASSWORD`.
- Removed explicit `/docs` and `/openapi.json` Caddy routes.

## E. Repo-Specific Remediation Roadmap

### P0: Lock Admin Role Resolution to Real Credentials

Summary: Remove Origin/Referer-only admin role assignment.

Why it matters: Origin headers are not credentials.

Approach: Change `resolve_role()` so admin role requires verified API key or a
valid admin JWT. Add regression tests for forged Origin/Referer.

Complexity: Medium

Risk of change: Medium

Owner: Backend

### P1: Enforce Production Web Admin Password at Startup

Summary: Fail deployment early when `ADMIN_PASSWORD` is missing in production.

Why it matters: Request-time fail-closed behavior protects requests, but startup validation
produces clearer operator feedback.

Approach: Add a small Next/server env validation or deployment smoke check.

Complexity: Small

Risk of change: Low

Owner: Frontend / DevOps

### P2: Protect Metrics as an Internal-Only Surface

Summary: Add a metrics allowlist or separate internal metrics listener.

Why it matters: Metrics should not depend only on host firewall posture.

Approach: Keep Caddy from routing `/metrics`, bind API localhost-only, and
consider requiring a metrics token or internal source IP.

Complexity: Small to medium

Risk of change: Low

Owner: Platform / Backend

### P3: Harden Admin Log Access

Summary: Align log allowlists, redact sensitive patterns, and audit log views.

Why it matters: Logs can contain secrets and private operational detail.

Approach: Share one allowlist constant/config between API and sidecar, lower
default line count, redact token-like values, and emit an audit event per access.

Complexity: Medium

Risk of change: Low

Owner: Backend / Platform

### P4: Create a Mounted-Router Security Registry

Summary: Document active versus dormant routers and required auth dependencies.

Why it matters: The repo contains substantial dormant auth, billing, analytics,
golf, and webhook code. Future mounting should not accidentally expose it.

Approach: Add a small docs table and tests that assert mounted routers have the
expected auth dependency.

Complexity: Small

Risk of change: Low

Owner: Backend

### P5: Standardize Model Artifact Loading

Summary: Require signed artifact loading for all analytics model loads.

Why it matters: Pickle/joblib are safe only for trusted local artifacts.

Approach: Replace direct `joblib.load()` calls with the signed loader where
possible and add a static test preventing direct loads outside approved modules.

Complexity: Medium

Risk of change: Medium

Owner: Backend / ML

### P6: Move CSP Toward Nonces or Hashes

Summary: Remove inline script allowance when Next/Twitter constraints are solved.

Why it matters: Strong CSP reduces XSS impact.

Approach: Prototype nonce wiring in the Next request gate, then narrow script/style
directives.

Complexity: Medium to large

Risk of change: Medium

Owner: Frontend / Security

### P7: Add Secret and Dependency Scanning Gates

Summary: Add CI jobs for secret scanning and dependency vulnerability review.

Why it matters: Local env files and broad dependency sets make automation
valuable.

Approach: Use GitHub secret scanning where available, add a local secret scanner
or pre-commit hook, run `pnpm audit` and Python dependency audit in CI with an
agreed severity threshold.

Complexity: Small to medium

Risk of change: Low

Owner: DevOps / Security

## F. Security Testing Recommendations

Add or keep these checks:

- Next proxy-gate tests for every protected admin/proxy prefix.
- Backend tests proving `ADMIN_ORIGINS` alone cannot satisfy admin auth.
- Router mounting tests that assert admin routers use admin API-key dependency.
- Integration test that `/metrics` is not reachable through Caddy.
- Header tests for Caddy and Next security headers.
- Log endpoint tests for redaction and allowlist alignment.
- Static test banning direct `joblib.load()` except in approved signed-loader
  modules.
- Secret scanning in CI and pre-commit.
- Dependency audit CI for `pnpm` and Python lock/requirements once the team
  chooses standard tooling.

## G. Leadership Summary

The largest actual risk was the web proxy/admin boundary: a public Next surface
could proxy privileged backend requests with the server-side API key. That has
now been fixed for admin and privileged proxy paths.

The second practical risk was deployment exposure. Compose no longer binds API,
web, metrics, and observability ports to all interfaces, preserving Caddy as the
intended edge.

The backend has several reasonable controls already: production config
validation, API-key protection on active admin routers, security headers,
parameterized database access patterns, rate limiting, and signature-based model
loading in the core analytics loader.

Before broader exposure, the team should remove Origin/Referer-derived admin
authority, make metrics explicitly internal-only, and harden admin log access.
The remaining browser CSP, analytics artifact, and scanning items can be phased
in without blocking the current operational path.

Verdict: Prod posture has notable risk areas, with the highest-risk web proxy
and port-binding issues fixed in this pass. Remaining risk is concentrated in
backend auth semantics, operational surfaces, and future mounting of dormant
routers.
