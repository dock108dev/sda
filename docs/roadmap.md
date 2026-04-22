# Roadmap

## Status Key

- ✅ Done
- 🔄 In progress
- ⬜ Not started

---

## Phase 0 — Foundation ✅

DB schema, module boundaries, multi-tenant auth middleware.

- ✅ PostgreSQL baseline schema (migrations 001-056)
- ✅ JWT auth with signup/login/magic-link/password-reset (`api/app/routers/auth.py`)
- ✅ Role-based access control (`user`, `admin`)
- ✅ `AUTH_ENABLED` dev-bypass flag (blocked in production)
- ✅ Rate limiting middleware
- ✅ Sports data pipeline (NBA, NHL, NCAAB, MLB, NFL)

---

## Phase 1 — Commerce ✅

Stripe checkout, idempotent webhook handling, onboarding sessions.

- ✅ `stripe_customers`, `stripe_subscriptions`, `processed_stripe_events` tables (migration 058)
- ✅ `POST /api/v1/commerce/checkout` — create Stripe checkout session for a plan
- ✅ `POST /api/webhooks/stripe` — idempotent webhook handler; advances `onboarding_sessions` on `checkout.session.completed` and manages subscription lifecycle on `customer.subscription.*`
- ✅ Payment confirmation email on successful checkout
- ✅ Dunning email on `invoice.payment_failed`
- ✅ Plan price constants: `price_starter` ($29/mo), `price_pro` ($99/mo), `price_enterprise` ($299/mo)

---

## Phase 2 — Identity ✅

Account creation, magic-link claim, password reset.

- ✅ `magic_link_tokens` table (migration 060); `users.password_hash` now nullable
- ✅ `POST /auth/magic-link` + `POST /auth/magic-link/verify`
- ✅ `POST /auth/forgot-password` + `POST /auth/reset-password`
- ✅ `onboarding_sessions` table (migration 059) — two-token pattern (`session_token` + `claim_token`); states: `pending → paid → claimed → expired`
- ✅ `GET /api/onboarding/session/{token}` — frontend polling for session status
- ✅ `POST /api/onboarding/claim` — exchange claim token after payment

---

## Phase 3 — Club Provisioning ✅

Idempotent club + first pool creation, entitlement service.

- ✅ `club_claims` table (migration 057) — public "claim your club" form submissions
- ✅ `clubs` table (migration 061) — slug-keyed tenant records with plan, status, Stripe customer link
- ✅ `POST /api/onboarding/club-claims` — public form submission, triggers notification email
- ✅ `GET /api/v1/clubs/{slug}` — public club lookup with active pools
- ✅ `golf_pools.club_id` FK (migration 061) — club-scoped tenancy for pools
- ✅ `EntitlementService` — centralized plan limit enforcement; raises `EntitlementError` (→ 403) or `SeatLimitError` (→ 402)
- ✅ Global exception handlers for `EntitlementError`, `SeatLimitError`, `SubscriptionPastDueError`, `TransitionError`
- ✅ `audit_events` table (migration 063) — structured provisioning, payment, and lifecycle audit log
- ✅ `pool_lifecycle_events` table (migration 062) — pool state machine audit trail
- ✅ `webhook_delivery_attempts` table (migration 064) — async retry and dead-letter tracking
- ✅ Admin platform stats endpoint (`GET /api/admin/stats`, `GET /api/admin/poll-health`)

---

## Phase 4 — Pool Lifecycle ⬜

Zod config validation, state machine, admin pool management, tournament data.

- ⬜ Pool state machine enforced end-to-end: `draft → open → locked → live → completed`
- ⬜ Admin pool management: create/edit/transition from admin SPA
- ⬜ Zod discriminated union for pool config enforced on submission
- ⬜ Tournament data linked when pool moves out of draft
- ⬜ `GET /api/golf/pools/{id}/entries` — submission validation with pool-state guard
- ⬜ Pool config versioning (immutable snapshots on state transitions)

---

## Phase 5 — Public Entry ⬜

Submission validation, abuse prevention, path-based club routing.

- ⬜ `/clubs/{slug}/pools/{pool_id}/` public entry pages (web)
- ⬜ Entry rate limiting per IP and per email
- ⬜ Duplicate submission detection (same email + pool)
- ⬜ Entry confirmation email
- ⬜ Path-based club routing (Caddy or Next.js middleware)

---

## Phase 6 — Reporting & Export ⬜

Streamed CSV, leaderboard integration, dashboard summary.

- ⬜ `GET /api/golf/pools/{id}/export.csv` — streamed CSV of entries + scores
- ⬜ Leaderboard integration in dashboard
- ⬜ Club admin dashboard summary: entries, score runs, payment status
- ⬜ `SUBDOMAIN_ROUTING` / `BASE_DOMAIN` feature flag activated

---

## Phase 7 — Operational Visibility ⬜

Operator API, webhook retry, transactional emails, audit log.

- ⬜ Webhook retry queue — reprocess dead-letter events from `webhook_delivery_attempts`
- ⬜ Operator API for club/subscription status inspection
- ⬜ Transactional email for pool open/close/results
- ⬜ Admin audit log UI (surfacing `audit_events` table)

---

## Phase 8 — Multi-Admin & Branding ⬜

Club invites, custom branding gating, annual subscription lifecycle.

- ⬜ `club_memberships` invite flow fully wired (migration 065 exists, UI pending)
- ⬜ Custom branding: `clubs.branding_json` column populated via `PUT /api/v1/clubs/{id}/branding`
- ⬜ Annual subscription lifecycle (cancel_at_period_end, renewal emails)
- ⬜ Multi-admin seat limits enforced by `EntitlementService`

---

## Phase 9 — Hardening & Scale ⬜

Security checklist, subdomain routing, DB indexes, observability.

- ⬜ Security checklist: CSP headers, rate limit audit, secrets rotation guide
- ⬜ Subdomain routing activated (`SUBDOMAIN_ROUTING=true`)
- ⬜ Additional DB indexes for common query patterns (migration 066 adds initial set)
- ⬜ OpenTelemetry traces wired through club provisioning path
- ⬜ Load test: 1,000 concurrent pool entries

---

## Open Decisions

1. **Subdomain vs path-based routing** — Path-based (`/clubs/{slug}/`) is the default; `SUBDOMAIN_ROUTING` flag exists for future activation. See `docs/research/subdomain-vs-path-based-club-routing.md`.
2. **Magic-link expiry** — Currently 24h for onboarding tokens; revisit for security hardening.
3. **Annual plan pricing** — Monthly plans exist; annual billing requires `cancel_at_period_end` lifecycle handling.
4. **Pool config schema evolution** — Current Zod union covers RVCC/Crestmont variants; extensibility for new pool types undecided.
5. **Webhook retry strategy** — Dead-letter table exists; retry queue not yet implemented. See `docs/research/webhook-job-queue-options.md`.
