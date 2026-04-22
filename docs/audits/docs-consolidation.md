# Documentation Consolidation Audit — 2026-04-22

Full documentation review and rewrite to reflect the current state of the codebase.

---

## Deleted

| File | Reason |
|------|--------|
| `ARCHITECTURE.md` (root) | Meta-description placeholder — just said "ARCHITECTURE.md is written at...". Real content is in `docs/architecture.md`. |
| `DESIGN.md` (root) | Same meta-description pattern. Design principles live in `CLAUDE.md` and `docs/architecture.md`. |
| `BRAINDUMP.md` (root) | Pre-implementation planning doc for the club provisioning system. The implementation is now in the codebase; the research-level content is captured in `docs/research/`. Retaining it would create confusion about what is designed vs. built. |
| `docs/AUDIT_REPORT.md` | Superseded by individual audit files in `docs/audits/`. |
| `docs/audits/cleanup-report.md` | Ephemeral cleanup notes; no durable operational value. |
| `docs/audits/security-audit.md` | No content existed at the linked path. |
| `docs/golf-pools.md` | Deleted prior to this audit; golf pool API coverage moved into `docs/api.md` and `docs/architecture.md`. |
| `docs/jsonb-schemas.md` | Content covered by `docs/database.md` JSONB column inventory. |
| `docs/phase6-validation.md` | Ephemeral validation checklist; validation rules are in `docs/gameflow/timeline-validation.md`. |

---

## Created

| File | What It Contains |
|------|-----------------|
| `docs/clubs.md` | Complete reference for the club provisioning domain: onboarding flow, all 9 new API endpoints, entitlement error table, pool lifecycle state machine, Stripe configuration, idempotency design, audit log. |
| `docs/research/README.md` | Index of the 18 pre-implementation research documents in `docs/research/`, organized by topic area. |
| `docs/audits/docs-consolidation.md` | This file. |

---

## Rewritten

| File | Changes |
|------|---------|
| `ROADMAP.md` | Replaced meta-description placeholder with an actual phase-by-phase roadmap showing ✅/⬜ status for each deliverable. Phases 0–3 marked complete based on merged migrations (057–067) and new routers. Phases 4–9 marked as not started. Includes 5 open architectural decisions. |

---

## Updated

| File | Changes |
|------|---------|
| `docs/architecture.md` | Added "Club Provisioning Domain" as Component 5 — covers 7 new routers (onboarding, commerce, webhooks, clubs, billing, club_memberships, club_branding), `EntitlementService`, and pool lifecycle state machine. Fixed broken `../golf-pools.md` link. |
| `docs/database.md` | Added "Club Provisioning & Commerce" schema section with 11 new tables from migrations 057–067: `club_claims`, `clubs`, `club_memberships`, `onboarding_sessions`, `magic_link_tokens`, `stripe_customers`, `stripe_subscriptions`, `processed_stripe_events`, `pool_lifecycle_events`, `audit_events`, `webhook_delivery_attempts`. Updated `users` row to note `password_hash` is now nullable. |
| `docs/changelog.md` | Added `[2026-04-22]` entry covering the full club provisioning domain: all 11 migrations, 9 new endpoints, 4 new services. |
| `docs/index.md` | Fixed 5 broken links (`golf-pools.md`, `security-audit.md`, `docs-consolidation.md`, `research/README.md`, `gameflow/phase6-validation.md`). Added "Golf & Club Provisioning" section linking to `docs/clubs.md`. Removed the now-deleted "Phase 6 Validation" entry. |

---

## Verified Accurate (no changes needed)

- `docs/ops/deployment.md` — current and accurate
- `docs/ops/infra.md` — current and accurate
- `docs/ops/runbook.md` — current and accurate
- `docs/analytics.md` — well-structured, accurate
- `docs/analytics-downstream.md` — accurate
- `docs/adding-sports.md` — accurate
- `docs/gameflow/` (all 6 files) — accurate
- `docs/ingestion/data-sources.md` — accurate
- `docs/ingestion/odds-and-fairbet.md` — accurate
- `docs/ingestion/ev-math.md` — accurate
- `docs/audits/abend-handling.md` — current (dated 2026-04-22)
- `docs/audits/ssot-cleanup.md` — current (dated 2026-04-22)
- `docs/conventions/db.md` — accurate
- `docs/research/` (all 18 files) — accurate as pre-implementation research

---

## Remaining Gaps

- `docs/api.md` — does not yet have sections for the 9 new club provisioning endpoints (billing, commerce, clubs, onboarding, webhooks, club_branding, club_memberships, admin/audit, admin/platform). The new `docs/clubs.md` covers these endpoints. A future pass should add them to `docs/api.md` for completeness.
- `docs/architecture.md` and `docs/database.md` do not yet cover the `v1/games.py` consumer-facing read-only API (minor gap — it's a thin read layer over sports_games).
