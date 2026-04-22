# Research Notes

Pre-implementation design research. Each file documents a technical decision area — the tradeoffs, options evaluated, and the approach that was chosen.

These are reference documents, not operational guides. The implementations they informed are in the codebase.

## Commerce & Payments

| Document | Topic |
|----------|-------|
| [stripe-checkout-webhook-patterns.md](stripe-checkout-webhook-patterns.md) | Stripe checkout session lifecycle, idempotent webhook handling, `processed_events` pattern |
| [stripe-subscription-vs-one-time-lifecycle.md](stripe-subscription-vs-one-time-lifecycle.md) | Subscription vs one-time payment tradeoffs, `cancel_at_period_end` lifecycle |
| [onboarding-session-recovery-pattern.md](onboarding-session-recovery-pattern.md) | Two-token onboarding pattern (session_token + claim_token), concurrent payment handling |

## Identity & Auth

| Document | Topic |
|----------|-------|
| [magic-link-vs-password-auth.md](magic-link-vs-password-auth.md) | Tradeoffs between magic-link and password auth for club provisioning |

## Club & Multi-Tenancy

| Document | Topic |
|----------|-------|
| [multi-tenant-club-scoped-rbac.md](multi-tenant-club-scoped-rbac.md) | Club-scoped RBAC design, middleware stack, role enforcement |
| [idempotent-provisioning-patterns.md](idempotent-provisioning-patterns.md) | Three-layer idempotency for club provisioning (HTTP → DB → state machine) |
| [subdomain-vs-path-based-club-routing.md](subdomain-vs-path-based-club-routing.md) | Subdomain vs path-based routing for club pages; current default is path-based |

## Pool Management

| Document | Topic |
|----------|-------|
| [pool-lifecycle-state-machine.md](pool-lifecycle-state-machine.md) | Pool states (draft/open/locked/live/completed), transition guards, audit events |
| [pool-config-json-schema-validation.md](pool-config-json-schema-validation.md) | Zod discriminated union for pool config, Pydantic mirror |
| [pool-duplication-semantics.md](pool-duplication-semantics.md) | Pool duplication for recurring tournaments |

## Entitlements & Rate Limiting

| Document | Topic |
|----------|-------|
| [entitlement-enforcement-patterns.md](entitlement-enforcement-patterns.md) | Centralized EntitlementService, plan limits, error hierarchy |
| [public-entry-rate-limiting-abuse-prevention.md](public-entry-rate-limiting-abuse-prevention.md) | Entry rate limiting per IP and per email, abuse prevention |

## Golf Tournament Data

| Document | Topic |
|----------|-------|
| [golf-tournament-data-apis.md](golf-tournament-data-apis.md) | DataGolf API coverage, sync cadence, field/leaderboard/odds data |
| [existing-sda-tournament-player-data.md](existing-sda-tournament-player-data.md) | Existing tournament and player tables in SDA |
| [existing-sda-leaderboard-scoring-engine.md](existing-sda-leaderboard-scoring-engine.md) | Current golf pool scoring engine, RVCC/Crestmont variants |

## Operations

| Document | Topic |
|----------|-------|
| [webhook-job-queue-options.md](webhook-job-queue-options.md) | Webhook retry strategies, dead-letter queue options |
| [csv-streaming-export-nodejs.md](csv-streaming-export-nodejs.md) | Streamed CSV export approach for large pool entry sets |
| [operator-admin-tooling-options.md](operator-admin-tooling-options.md) | Operator API design, admin tooling options |
