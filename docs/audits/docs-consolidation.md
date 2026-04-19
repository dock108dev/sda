# Documentation Consolidation Audit

> Branch: `aidlc_1` — Date: 2026-04-18

## Summary

47 documentation files audited across the repo. No files deleted (all carry unique value). No files moved (root docs are referenced by `CLAUDE.md` and must stay in place). Six files updated to fix factual errors or stale content introduced by the `aidlc_1` SSOT cleanup changes.

---

## Files Changed

### `ARCHITECTURE.md` (root)

**Problem:** Multiple stale and incorrect statements relative to the current codebase.

**Changes made:**

| Section | Old | New |
|---------|-----|-----|
| `scraper/` components | Listed "Analytics/ML" as a scraper component | Removed — analytics lives in `api/app/analytics/`, not the scraper |
| `api/` components | No mention of analytics | Added analytics as an `api/` component with correct path |
| Web guardrails | Block count "(4–7)" | Corrected to "(3–7)" — both ends now use MIN_BLOCKS = 3 |
| Pipeline stage names | Old names: `normalize_pbp`, `drama_analysis`, `group_moments`, `generate_blocks`, `embedded_tweets`, `validate_blocks`, `finalize_moments`, `persist` | Corrected to actual enum names: `NORMALIZE_PBP`, `GENERATE_MOMENTS`, `VALIDATE_MOMENTS`, `ANALYZE_DRAMA`, `GROUP_BLOCKS`, `RENDER_BLOCKS`, `VALIDATE_BLOCKS`, `FINALIZE_MOMENTS` |
| Pipeline stage order | Drama analysis was stage 2; embedded_tweets was a standalone stage 5 | Correct order: moments generated/validated before drama; embed selection folded into `RENDER_BLOCKS` |
| Social ingestion note | "Embed selector (stage 5 of flow pipeline)" | "Embed selector (during `RENDER_BLOCKS` pipeline stage)" |
| State management | `GameStatus` "has duplicate cancelled/canceled; dedupe in Phase 2" | "Canonical value is `CANCELLED`" (fixed by SSOT cleanup migration) |
| State management | `PipelineStage` "currently duplicated in DB and service layers" | "Single SSOT in `api/app/services/pipeline/models.py`; db layer re-exports" |
| Directory structure | Listed `scraper/sports_scraper/pipeline/` and `analytics/` — neither exists | Removed both; added correct scraper subdirs (`jobs/`, `live/`, `persistence/`, `services/`) and `api/app/analytics/` |
| Known pressures | Listed "Enum duplication" and "Moments vs blocks vestige" as open | Removed — both resolved in `aidlc_1` |
| Known pressures | "Score tuple convention … Phase 2 moves to `{home, away}`" | Updated to reflect partial completion: consumer endpoint uses `ScoreObject`; admin endpoints still pending |
| Known pressures | Consumer/admin boundary phrasing | Updated to reflect `/api/v1/` game flow endpoint is now live |
| API router description | "All currently live under `/api/admin/sports/`; Phase 2 introduces `/api/v1/`" | Updated to reflect `/api/v1/` is live for game flow |

---

### `DESIGN.md` (root)

**Problem:** "Pipeline as ordered stages" paragraph referenced `scraper/sports_scraper/pipeline/` — a path that does not exist. Pipeline code lives in `api/app/services/pipeline/stages/`.

**Change:** Updated path to `api/app/services/pipeline/stages/`.

---

### `CLAUDE.md` (root)

**Problem:** "Where things live" section listed two wrong paths:
- `Pipeline stages: scraper/sports_scraper/pipeline/`
- `Flow validation: scraper/sports_scraper/pipeline/validate_blocks.py`
- `Frontend guardrails` had an "(or similar — verify path)" hedge that is no longer needed

**Changes:**
- Corrected both paths to `api/app/services/pipeline/stages/`
- Removed the unnecessary path-verification hedge on `guardrails.ts`

---

### `BRAINDUMP.md` (root)

**Problem:** Several specific claims were made stale by `aidlc_1` SSOT cleanup work.

**Changes:**

| Claim | Update |
|-------|--------|
| `GameStatus` duplicate `canceled` entry | Moved to "Resolved in `aidlc_1`" note; standardized to `CANCELLED` |
| `PipelineStage` defined in two places | Moved to resolved note; single SSOT now |
| Score tuples `[int, int]` on wire | Moved to resolved note; `ScoreObject` is the consumer contract |
| Moments in consumer API | Moved to resolved note; moments removed from `/api/v1/` |
| Priority 2: "Align MIN_BLOCKS" | Marked as done — both sides now 3, verified in sync |
| Priority 2: "Move scores to objects" | Marked as done (consumer endpoint); admin migration still pending |
| Priority 2: "Single PipelineStage enum" | Marked as done |
| Priority 2: "Document score convention" | Marked as done — `ScoreObject` is self-documenting |

---

## Files Audited and Unchanged

All remaining docs were verified accurate against the current codebase:

| File | Status |
|------|--------|
| `README.md` | Accurate. Concise. No changes. |
| `ROADMAP.md` | Accurate. Phase descriptions match current priorities. |
| `docs/index.md` | Accurate. All linked files exist. |
| `docs/architecture.md` | Accurate. Already had correct pipeline path (`api/app/services/pipeline/`) and correct stage names. |
| `docs/api.md` | Accurate. Endpoint reference matches router files. |
| `docs/database.md` | Accurate. Schema tables match Alembic baseline. |
| `docs/adding-sports.md` | Accurate. Analytics section already correctly references `api/app/analytics/`. |
| `docs/analytics.md` | Accurate. Engine description matches `api/app/analytics/`. |
| `docs/analytics-downstream.md` | Accurate. Integration guide is consistent with API. |
| `docs/gameflow/contract.md` | Accurate. Block spec matches `validate_blocks.py` constants. |
| `docs/gameflow/guide.md` | Accurate. TypeScript types consistent with `packages/js-core/`. |
| `docs/gameflow/pipeline.md` | Accurate. Stage names and order match actual code. |
| `docs/gameflow/pbp-assumptions.md` | Accurate. |
| `docs/gameflow/timeline-assembly.md` | Accurate. |
| `docs/gameflow/timeline-validation.md` | Accurate. |
| `docs/gameflow/version-semantics.md` | Accurate. `v2-blocks` is documented as current; `v2-moments` as deprecated with transition guidance. |
| `docs/ingestion/data-sources.md` | Accurate. All data source references are correct. |
| `docs/ingestion/ev-math.md` | Accurate. Shin's devigging formulas unchanged. |
| `docs/ingestion/odds-and-fairbet.md` | Accurate. Pipeline flow matches scraper code. |
| `docs/golf-pools.md` | Accurate. |
| `docs/ops/infra.md` | Accurate. Docker profile structure matches `infra/`. |
| `docs/ops/deployment.md` | Accurate. CI/CD description matches `.github/workflows/`. |
| `docs/ops/runbook.md` | Accurate. |
| `docs/changelog.md` | Present; not audited for correctness (changelog is append-only). |
| `docs/AUDIT_REPORT.md` | Accurate. All critical/high findings documented as fixed. |
| `docs/audits/abend-handling.md` | Present. |
| `docs/audits/security-audit.md` | Present. |
| `docs/audits/ssot-cleanup.md` | Accurate. Describes exactly what was changed in `aidlc_1`. |
| `docs/research/` (17 files) | Forward-looking research docs. Accuracy depends on implementation status of Phase 2–6 items. No claims made about current implementation state — these are design research docs. |

---

## What Was NOT Changed (and Why)

**Structure:** Root-level docs (`ARCHITECTURE.md`, `DESIGN.md`, `ROADMAP.md`, `BRAINDUMP.md`) were not moved to `/docs/`. `CLAUDE.md` is a Claude Code instruction file that must remain at root and references all four files by relative path. Moving them would break `CLAUDE.md` without adding value.

**No deletes:** Every doc file carries distinct content. There is overlap between root `ARCHITECTURE.md` (monorepo structure, data flow, component overview) and `docs/architecture.md` (operational depth, schema details, API endpoint reference), but they serve different audiences (system overview vs. developer reference) and are cross-linked appropriately.

**Research docs:** 17 forward-looking research documents in `docs/research/` were not modified. They are proposals and analysis docs for Phase 2–6 implementation decisions, not descriptions of current behavior. Their content is accurate for their purpose (providing context before implementing a feature).

---

## Remaining Documentation Gaps

These are known gaps that would require code-level investigation to resolve — not addressed in this doc-only review:

1. **Celery task orchestration** — no single doc describes the full task graph (which tasks dispatch which others, retry policies, hold mechanism). The information is spread across `DESIGN.md`, `docs/ops/runbook.md`, and the research docs.
2. **WebSocket/SSE protocol spec** — sequence tracking, boot epoch, reconnect + backfill behavior are described in `DESIGN.md` conventions and the research doc but there is no authoritative message format spec.
3. **NCAAB fuzzy team matching algorithm** — referenced in `docs/architecture.md` (Levenshtein distance) but not documented in a dedicated doc.
4. **`v2-moments` → `v2-blocks` migration status** — `docs/gameflow/version-semantics.md` says to remove `_LEGACY_FLOW_VERSION` after all rows are migrated, but there is no ops procedure for confirming when that is complete.
