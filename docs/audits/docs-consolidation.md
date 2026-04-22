# Documentation Consolidation Audit — 2026-04-22 (Pass 2)

Second pass, following the earlier 2026-04-22 consolidation. The prior pass
rewrote most documentation against the current codebase; this pass enforces the
"README.md at root, everything else under `/docs`" rule and closes the known
gap between `docs/clubs.md` and `docs/api.md`.

---

## Root cleanup (moved)

Per the rule "Critical docs live in root (README.md only)":

| From | To |
|------|----|
| `ROADMAP.md` | `docs/roadmap.md` |
| `AIDLC_FUTURES.md` | `docs/audits/aidlc-futures.md` |

`CLAUDE.md` stays at root — it is an agent instruction file, not a project
doc. `README.md` is unchanged; its "Further Documentation" pointer to
`docs/index.md` still holds.

The AIDLC tooling will regenerate `AIDLC_FUTURES.md` at the root on its next
finalization run; that behavior is a tooling concern and not in scope for this
doc pass.

---

## Updates

| File | Change |
|------|--------|
| `docs/index.md` | Added `roadmap.md` under **Getting Started**. Added entries for `audits/security-audit.md`, `audits/cleanup-report.md`, and `audits/aidlc-futures.md` (these files exist on disk and were previously unlinked from the index). |
| `docs/api.md` | Added a new **Club Provisioning & Commerce** section at the end listing the 9 endpoints (`/api/onboarding/*`, `/api/v1/commerce/checkout`, `/api/webhooks/stripe`, `/api/v1/clubs/{slug}`, `/api/v1/billing/portal`, `/api/v1/clubs/{id}/branding`, `/api/admin/audit`) with a pointer to `docs/clubs.md` for full request/response shapes. Closes the gap called out as "Remaining Gaps" in the prior pass. |

---

## Verified accurate (no changes)

Spot-checked against the codebase via an explore pass; all content matches
current reality:

- `README.md` — repo layout, local dev command, doc pointer all correct
- `CLAUDE.md` — design principles and layout match `api/`, `scraper/`, `web/`,
  `packages/`
- `docs/architecture.md` — Component 5 "Club Provisioning" matches the 7
  routers under `api/app/routers/` (onboarding, commerce, clubs, billing,
  club_branding, club_memberships, webhooks)
- `docs/database.md` — club provisioning tables from migrations 057–067
  match `api/alembic/versions/`
- `docs/clubs.md` — endpoint list matches the routers under
  `api/app/routers/`
- `docs/adding-sports.md` — dual SSOT pattern (`scraper/sports_scraper/config_sports.py`
  + `api/app/config_sports.py`) matches code
- `docs/analytics.md`, `docs/analytics-downstream.md` — sport modules match
  `api/app/analytics/sports/{mlb,nba,nhl,ncaab,nfl}/`
- `docs/gameflow/*` (6 files) — pipeline stages, contract, validation rules
  all match code
- `docs/ingestion/{data-sources,odds-and-fairbet,ev-math}.md` — match scraper
  code
- `docs/ops/{infra,deployment,runbook}.md` — match infra assets
- `docs/conventions/db.md` — matches naming used in Alembic migrations
- `docs/research/` (18 files + README) — pre-implementation research,
  correctly labeled; kept as design records
- `docs/audits/{abend-handling,ssot-cleanup,security-audit,cleanup-report}.md`
  — current-branch audit artifacts dated 2026-04-22

---

## Not deleted (reviewed and kept)

- `docs/audits/cleanup-report.md` — the earlier pass flagged this as
  "ephemeral", but the current file on disk is a concrete, useful record of
  the observability / security-hardening import-cleanup batch. Kept as an
  audit-trail artifact and linked from `docs/index.md`.
- `docs/audits/security-audit.md` — the earlier pass claimed it was empty;
  the current file is a substantive 141-line security review with concrete
  findings (CSP, public pool enumeration, etc). Kept and linked.
- `docs/changelog.md` — large (~102 KB) but actively maintained; the most
  recent entry is the 2026-04-22 club provisioning rollout. No changes.

---

## Remaining gaps / follow-ups

- `docs/api.md` now references the club endpoints by path and method, but
  the full per-endpoint request/response shapes live only in `docs/clubs.md`.
  A future pass could inline the request/response examples from `clubs.md`
  into `api.md` to keep `api.md` as the single endpoint reference, then slim
  `clubs.md` to a domain / flow doc. Deferred — duplicating content now would
  create two places that could drift.
- `docs/architecture.md` and `docs/database.md` still do not call out
  `api/app/routers/v1/games.py` as the thin consumer-facing read layer
  over `sports_games`. Minor.
- The AIDLC tooling regenerates `AIDLC_FUTURES.md` at the repo root.
  Long-term fix would be to configure AIDLC to write under `docs/audits/`
  directly; out of scope here.
