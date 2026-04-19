# Design Patterns & Conventions

## Code Organization

- **Per-sport modules, shared base classes.** Ingestion, schemas, and stat models are split per sport (NBA, NHL, MLB, NFL, NCAAB, golf) but inherit from common base types for cross-sport operations (game list, odds, flow pipeline).
- **Thin routers, thick services.** FastAPI routers parse + validate + delegate. Business logic lives in `api/app/services/`. Routers contain no SQL.
- **Pipeline as ordered stages.** Each stage in `api/app/services/pipeline/stages/` is a pure function of (prior stage output, game data) → new output. No stage reads from the DB; the orchestrator handles persistence.
- **Shared types in `packages/js-core/`.** Any type crossing the API boundary has a TS mirror here. Handwritten, not generated — OpenAPI generation tooling has not held up against our nullable/alias patterns.

## API Conventions

- **camelCase in responses.** All Pydantic response models use `Field(alias=...)` + `populate_by_name = True`. snake_case is internal; camelCase crosses the wire. Phase 2 adds a lint check for missing aliases.
- **Score object, not tuple.** Target convention (Phase 2): `{home: int, away: int}` everywhere. Current tuple + `_swap_score()` pattern is deprecated. See `docs/research/pydantic-score-object-migration.md`.
- **Non-nullable computed predicates.** `isLive`, `isFinal`, `isPregame` are booleans, never null. Nullable booleans force defensive checks on the client for no semantic reason.
- **Versioned namespace.** Consumer endpoints under `/api/v1/`, admin under `/api/admin/`. Different auth, different rate limits, different response shapes allowed. See `docs/research/fastapi-api-versioning-patterns.md`.
- **Explicit enums over magic strings.** Any finite set is a Pydantic `Enum`. Frontend receives string values; TS union types mirror them.

## Database Conventions

- **SQLAlchemy 2.0 async, typed mappers.** Declarative models with `Mapped[...]` annotations; session dependency injected into services.
- **Alembic with squash strategy.** Long-lived branches squash migrations before merge. Enum changes use the add-new-value-then-rename pattern to stay online. See `docs/research/alembic-enum-sync-strategies.md`.
- **JSONB for genuinely flexible data only.** `raw_payloads` for provider blobs, `derived_metrics` for computed extras. Anything we query on gets a proper column. JSONB CHECK constraints added in Phase 2. See `docs/research/jsonb-schema-validation-postgres.md`.
- **Indexes on hot paths.** `(game_id, created_at)` on plays/posts, partial indexes on `status IN ('LIVE','SCHEDULED')`. Benchmarked, not speculative.
- **Cascades explicit.** Every FK declares `ondelete`. Game deletion cascades to boxscores, plays, flows, social posts.

## Celery Conventions

- **Queue per concern.** `sports-scraper`, `social-scraper`, `social-bulk`, `training`. Social bulk separated so interactive scrapes aren't blocked by backfills.
- **Redis NX lock per unique task key.** Prevents double dispatch from retry/duplicate-event paths.
- **Task expiry set explicitly.** Tasks that don't run within window are dropped, not queued indefinitely.
- **Admin hold mechanism.** Single Redis flag pauses all scrapers without worker restart.
- **Orphan detection on worker boot.** Tasks stuck in `STARTED` past TTL are reset.
- **Event-driven over beat.** Preferred dispatch pattern: ingestion-side ORM hooks or `LISTEN/NOTIFY`. Beat only for true cron (daily sweeps, reports). See `docs/research/celery-event-driven-vs-beat-scheduling.md` and `docs/research/event-driven-celery-task-dispatch.md`.

## Narrative Pipeline Conventions

- **Deterministic grouping, AI narration.** Moments and block structure are deterministic given the same PBP input. Only the prose is LLM-generated. This keeps regression tests stable.
- **3-layer system prompt.** Stable narrator identity + game-specific data + guardrail postscript. Don't mix stable and volatile content in the same prompt layer.
- **2-pass rendering.** Per-block generation, then game-level flow smoothing. Single-pass produces disjointed blocks.
- **Validation before publish.** Every flow passes structural + factual + quality scoring. Below threshold → regenerate (max 2) → template fallback. Fallback is the floor.
- **Template fallback is a first-class output path.** Not a bug state. Templates must be tested per sport per game shape (OT, blowout, incomplete PBP). See `docs/research/sport-specific-narrative-structure.md`.
- **Coverage requirements.** Every flow mentions final score, winning team, OT if present. Enforced in `validate_blocks.py` in Phase 1. See `docs/research/nlg-coverage-validation-techniques.md`.
- **Regen with error context.** When regenerating, include the quality-score breakdown of the failed attempt in the prompt. Blind regen converges poorly.

## Realtime Conventions

- **Sequence numbers + boot epoch.** Every pub/sub event carries `(epoch, seq)`. Clients detect gaps and request backfill. Epoch changes on server restart.
- **First-subscriber callback.** Channels don't poll until they have a listener. No-op channels cost nothing.
- **SSE for consumer, WebSocket for admin.** SSE reconnects automatically, is firewall-friendly, and matches the read-only consumer pattern. WebSocket reserved for bidirectional admin cases. See `docs/research/websocket-sse-react-integration-patterns.md`.
- **Patches, not replacements.** Live updates send score/clock deltas; full refetch only on period/phase change.
- **Differentiate staleness from liveness.** `dataStalenessState` is server-computed at response time with per-state thresholds. Frontend should not re-derive; single source of truth. See `docs/research/redis-pubsub-vs-streams-for-realtime.md` and `docs/research/postgres-listen-notify-python.md`.

## Testing Conventions

- **Golden corpus is load-bearing.** Every pipeline change runs against 10 games/sport (25/sport post-Phase 6). CI blocks on regression. See `docs/research/golden-corpus-construction-methodology.md`.
- **LLM-graded output, not just heuristics.** Heuristic quality scoring (repetition, vocab, readability, cliche) screens; LLM grader judges coherence. See `docs/research/llm-narrative-grading-patterns.md` and `docs/research/sports-narrative-quality-benchmarks.md`.
- **Fixtures from real PBP.** Unit-test pipeline stages against real PBP snapshots. Synthetic fixtures hide edge cases.
- **Frontend contract tests.** TS types must compile against the actual OpenAPI schema dump; CI runs both together.

## Observability Conventions

- **OpenTelemetry end-to-end.** Traces span HTTP → Celery task → LLM call → DB write. Metrics for stage durations, regen counts, fallback rates per sport. See `docs/research/opentelemetry-for-pipeline-observability.md`.
- **Alert on trust-killers first.** Score mismatches vs authoritative final, social collection dropouts, credit-quota burn, flow coverage gaps. These before latency SLOs.
- **Quality score histogram is a first-class chart.** Shifts here indicate prompt or data drift before users notice.

## Failure-Mode Conventions

- **Graceful degradation beats hard failure.** Template fallback for flows, cached Redis snapshot for odds, "recap pending" state instead of 404.
- **Every external dependency has a budget.** Odds API credits, OpenAI tokens, Playwright sessions. Burn projections alert before exhaustion.
- **No silent nulls on contract fields.** If the backend can't compute it, return an explicit unknown state (e.g. `gamePhase: "UNKNOWN"`) not `null`. Null means "field wasn't populated," which is an operational bug, not a semantic value.

## What We Don't Do

- **No ORM-side business logic.** Models hold shape + relationships. Services hold rules.
- **No per-endpoint score swap.** Use the shared helper (or the object type post-Phase 2).
- **No sentiment analysis on official team tweets.** They're announcements, not sentiment. See `docs/research/x-twitter-data-alternatives.md` for where sentiment could apply later.
- **No real-time partial narrative generation.** Flow pipeline is post-FINAL only. Live narration is a different product.
- **No backwards-compat shims for pre-Phase-2 contracts once migrated.** Cut cleanly; don't accumulate legacy.
