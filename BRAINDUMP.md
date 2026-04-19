# Backend Braindump

After digging through the full backend, scraper, and the completed Phase 1 frontend, here is what I actually think.

---

## Scroll-down-web handoff: Playwright, BFF, and what SDA must hold

This section is a **brainsump refresh** distilled from two consumer-side audits: **`SDA_HANDOFF.md`** (Playwright coverage map, CI policy, route inventory) and **`MINIMAL_SDA_FIXTURES.md`** (minimal JSON shapes and invariants). It is written for **this repo** (sports-data-admin / sports data API) as the upstream that scroll-down-web’s Next.js BFF calls with `SPORTS_DATA_API_KEY` (or equivalent).

### CI policy on the consumer (`@live-upstream`)

| Layer | Command / workflow | Intent |
|--------|----------------------|--------|
| **PR** | Playwright with `--grep "@smoke"` and `--grep-invert "@live-upstream"` | UI + BFF smoke **without** requiring live schedules, FairBet slates, or golf leaderboards from SDA. |
| **Daily** | Full Playwright | Includes `@live-upstream` tests that hit **real (or production-like)** upstream data through the web BFF. |

**Tag rule (consumer repo):** mark `@live-upstream` on any spec that needs non-empty games/odds/golf/history from SDA or that would skip/fail on an empty slate. **Do not** tag pure mocks, fixture-only `/api/ai/*` tests, or checks that only assert a non-5xx response.

**Implication for SDA:** PRs here are not blocked by consumer daily E2E, but **prod regressions** still surface in consumer daily runs. When daily fails, triage maps **failing test title → BFF route → upstream path** (see below).

### BFF routes the browser tests care about (consumer → upstream mental model)

The consumer app implements **`/api/*`** under its own `web/src/app/api/`. Those handlers forward to **this** API (e.g. admin sports routes). Playwright **explicitly** references strings like `/api/games`, `/api/fairbet`, `/api/golf/*`, `/api/history`; **implicitly**, loading `/`, `/game/[id]`, `/fairbet`, `/golf`, `/history` pulls the same BFF surface.

| Consumer BFF (examples) | Typical SDA responsibility |
|-------------------------|----------------------------|
| `GET /api/games`, `GET /api/games/*` | List + detail + flow-related data; must yield **renderable** game rows when tests expect data. |
| `GET /api/fairbet`, `/api/fairbet/odds`, `/api/fairbet/live` | Odds/EV cards, live FairBet; **numeric consistency** (EV, implied prob, cross-book) is an SDA concern. |
| `GET /api/golf/leaderboard`, `/api/golf/tournaments` | Tournament and leaderboard payloads for golf specs. |
| `GET /api/history` | History tier: pro vs free (`403` + `pro_required` where tests expect gating). |

Exact BFF implementation lives in **scroll-down-web** (`web/src/app/api/**/route.ts`). Upstream paths are often under **`/api/admin/sports/...`** (and consumer flow may use **`/api/v1/...`** where that split exists). This repo should treat **admin + v1** contracts as the source of truth for payloads the BFF proxies or reshapes.

### Minimal invariants (from `MINIMAL_SDA_FIXTURES.md`)

Use these when reproducing consumer Playwright failures or when stubbing the BFF locally.

**1. Games list (`GET` equivalent upstream: games list used by home)**  
- **Invariant:** `200` JSON with `games: GameSummary[]`; at least one row must be **renderable** on `/` (`[data-testid='game-row']` in consumer tests).  
- **High-signal fields:** `id`, `leagueCode`, `gameDate`, `status`, `homeTeam`, `awayTeam`; optional `homeScore`, `awayScore`, `hasFlow`, `hasOdds`, `isLive`, plus any **ingestion / freshness** fields the BFF exposes (consumer derives staleness UI from those).  
- **Empty slate:** many tests skip with “No game data available.” For **stable** daily E2E, SDA (or a fixture environment) should expose **at least one game per league** the UI shows (e.g. MLB, NBA, NCAAB, NHL) for a **stable date window**.

**2. FairBet (`/fairbet` → fairbet BFF routes)**  
- **Invariant:** Within timeout, either at least one `[data-testid='bet-card']` **or** `[data-testid='fairbet-empty-state']` (empty is valid).  
- **When cards exist:** smoke tests expect EV / tier / book row / attribution / line-movement **regions** to exist; **SDA owns numeric correctness**; consumer asserts presence and coarse behavior (blur, pro gate, etc.).

**3. History (`GET /api/history?…` on consumer)**  
- **Invariant:** For pro tier (cookie or `?tier=pro`), response must allow `/history` to render `[data-testid='page-history']` when authorized; free tier returns **`403`** with `pro_required` where gated tests expect it.  
- Date ranges in tests may be **fixed**; SDA should either return **stable** payloads for those params or document supported windows.

**4. Phase 9 book-details blur (consumer stub)**  
- Consumer **`fairbet/phase9.spec.ts`** may stub `**/api/fairbet/odds**` with a minimal `BetsResponse`-shaped JSON so blur/layout tests run without a full odds feed. **SDA must still satisfy section 2 in production**; the stub only documents **minimum card shape** for those assertions.

### What to give the consumer team from SDA

1. **Stable regression windows:** known dates + leagues with guaranteed non-empty games list (and optional FairBet/history) for `@live-upstream` daily runs.  
2. **Failing test titles** from daily Playwright → map to BFF route → **exact upstream endpoint + query** this repo serves.  
3. **Non-goals for SDA:** layout, focus order, Pro copy, PWA, Stripe, magic-link UX — **web-only**.

### Spec areas that typically carry `@live-upstream` (consumer repo)

FairBet (multiple specs), home/game list and cache/perf, game detail/timeline/stats, golf leaderboard/tournaments, history page, ads/mobile/freemium/realtime suites — see consumer `rg '@live-upstream' web/tests` for the live list.

---

## What the backend actually is right now

This is a real platform. Not a prototype pretending to be one. FastAPI + SQLAlchemy 2.0 async + Celery + Redis + Postgres. Two separate process trees: an API server and a scraper worker. The API handles routes, realtime (WS/SSE), and analytics tasks. The scraper handles ingestion, odds, social, and flow generation.

What is mature:
- The database schema. 23+ model files, proper FKs, cascades, JSONB columns where flexible data makes sense, indexes on the hot paths. Migrations are managed with Alembic and there's a squash strategy. This is not accidental — someone thought about it.
- Odds pipeline. Multi-book ingestion from The Odds API, closing line capture on LIVE transition, FairBet EV analysis with configurable devigging, Redis-backed caching with 15s TTL. Credit quota tracking. This is the most production-hardened vertical in the backend.
- The game flow pipeline. 8-stage pipeline with clear stage separation, deterministic grouping, AI narrative generation via OpenAI, multi-layer validation (structural + factual + quality scoring + decision engine), and graceful degradation to templates. This is architecturally sound. Whether the output is actually good enough is a separate question (more below).
- Auth and rate limiting. API key + JWT, constant-time comparison, role-based access, configurable rate limits per endpoint. Not glamorous but correct.
- Task infrastructure. Celery with proper queue separation (sports-scraper, social-scraper, social-bulk, training), Redis locks, admin hold mechanism, task expiry, orphan detection on worker restart. The operational story here is solid.

What is transitional:
- Realtime. The in-memory pub/sub manager with WebSocket + SSE exists, works, has sequence tracking and first-subscriber callbacks. But it's single-instance. The DB poller runs against Postgres every 1-5 seconds. The poller itself has a TODO comment saying "replace DB polling with Postgres LISTEN/NOTIFY." This works for now but will not scale past a single API process.
- Social ingestion. Playwright-based X scraping with session cookies. Rate-limited at 300 req/15min with a circuit breaker. This is functional but fragile. Cookie expiration requires manual refresh. No fallback API. This is the most operationally brittle subsystem.
- Advanced stats for NHL/NFL. MoneyPuck ZIP downloads and nflverse parquet files. These work but are not auto-updating pipelines — they depend on external file availability with 1-24 hour latency.
- Analytics/ML. Model registry, feature configs, training jobs, backtesting, experiment framework, Monte Carlo simulation. The infrastructure is there but the maturity of the actual models and their integration into the product is unclear. This feels like a parallel workstream that isn't yet load-bearing for the consumer experience.

What is legacy:
- The timeline artifact system. There are two parallel output paths: `SportsGameFlow` (moments + blocks) and `SportsGameTimelineArtifact` (timeline JSON). The flow path is the real one now. The timeline artifact feels like a v1 that hasn't been cleaned up. The frontend doesn't use it for the primary game flow view.
- The `external_ids` and `external_codes` JSONB fields on games and teams have no schema enforcement. They're catch-all bags with no documentation. This is fine until someone depends on a key that only sometimes exists.

> **Resolved in `aidlc_1`:** `GameStatus` duplicate `canceled` entry standardized to `CANCELLED`. `PipelineStage` enum now has a single SSOT in `api/app/services/pipeline/models.py`. Score tuple convention replaced with `ScoreObject {home, away}` on consumer endpoint. Moments removed from the consumer API (`/api/v1/`); blocks are the only consumer output.

---

## Where the backend fully supports the frontend (and where it does not)

### Fully covered

- **Game list with filters.** Backend returns `GameSummary` objects with all the `has*` flags, timestamps, team colors, state predicates. Frontend consumes this cleanly through the proxy. Pagination via `nextOffset`. This works.
- **Game detail.** Sport-specific player stats (basketball, hockey, baseball, football), team boxscores, odds, plays, derived metrics, raw payloads. The schema is comprehensive across 5 sports. Advanced stats for NBA, NHL, MLB, NFL, NCAAB all have dedicated schemas with proper camelCase aliasing.
- **Pipeline admin.** Start/continue/rerun pipeline, stage inspection, bulk generation. The admin panel can drive the pipeline. This is well-wired.
- **Golf.** DataGolf integration for tournaments, players, leaderboards, pools. This is a clean, self-contained vertical.
- **FairBet/odds.** EV analysis, live odds, consensus computation. Frontend has full UI for this and backend delivers.

### Incomplete or thin

- **Game flow blocks.** The backend pipeline produces 3-7 narrative blocks with roles, narratives, play IDs, key play IDs, score transitions, and clocks. The frontend is fully built to consume this — `CollapsedGameFlow.tsx` renders block cards with role badges, score changes, period ranges, mini box scores, and embedded tweet indicators. The guardrails module enforces 4-7 blocks, max 5 embedded tweets, 20-60 second read time. **But**: the backend's block generation runs on a daily scheduled job (4:30-6:30 AM EST per sport). There is no on-demand generation triggered by the frontend. If a game goes final at 11 PM and someone looks at it at 11:30 PM, there is no flow. The admin can manually trigger it, but the consumer experience has a gap here.
- **Mini box scores.** The frontend expects `miniBox` on each block with cumulative stats + segment deltas (`deltaPts`, `deltaGoals`, `deltaRuns`, etc.) and `blockStars` (last names). The backend pipeline's `NarrativeBlock` dataclass includes `mini_box` but it is unclear whether the actual pipeline stages are populating this consistently. The `finalize_moments.py` stage does a straight passthrough of block data — if `mini_box` isn't populated upstream, it's null in the DB, and the frontend gets nothing. This needs verification across all sports.
- **Social post phase categorization.** The frontend's `GameFlowView` expects `SocialPostsByPhase` (pregame, inGame by segment, postgame). The backend stores `game_phase` on `TeamSocialPost` but it's nullable and the mapping logic (`tweet_mapper.py`) may not reliably categorize all posts. The `ExpandableSocialSections` component groups by phase — if `game_phase` is null, those posts fall into limbo. The backend needs to guarantee phase assignment for all mapped posts.
- **Embedded social post IDs.** Blocks can reference `embedded_social_post_id` but the pipeline stage that assigns these (`embedded_tweets.py`) needs to actually resolve valid post IDs that the frontend can use. If the ID doesn't correspond to a real `TeamSocialPost`, the frontend renders "Social post #undefined" which is a trust problem.
- **Data staleness.** The backend computes `dataStalenessState` at API response time via `data_freshness.py` with configurable thresholds (live: 60s stale / 300s very_stale, pregame: 600s / 1800s). But this field is nullable in the response schema. The frontend uses 7-day and 1-day thresholds for its own staleness indicators. These are two different staleness models talking past each other. SSOT needed.
- **Score display convention.** Internal DB format is `[home, away]`. API swaps to `[away, home]` via `_swap_score()`. Frontend renders as "Away-Home". This works but is fragile — one missed swap in a new endpoint and scores are backwards. This convention should be documented as a hard contract, not a per-endpoint implementation detail.

### Where the frontend is ahead of the backend

- **Guardrails enforcement.** The frontend has `guardrails.ts` with hard invariants (max blocks, max tweets, word count limits, social independence validation). The backend has its own `validate_blocks.py` with overlapping but not identical constraints.

  > **Resolved in `aidlc_1`:** `MIN_BLOCKS` is now 3 in both `block_types.py` (backend) and `guardrails.ts` (frontend). Constants are in sync.

- **Consumer-facing game flow components.** `CollapsedGameFlow.tsx`, `GameFlowView.tsx`, `ExpandableSocialSections.tsx` are fully built and production-ready.

  > **Resolved in `aidlc_1`:** `/api/v1/` router namespace is live. Consumer game flow endpoint is at `/api/v1/games/{game_id}/flow`. Admin endpoints remain under `/api/admin/sports/`. Full consumer/admin split is Phase 2.

- **Baseball stat display.** The frontend `MiniBoxDisplay` checks for hockey-specific stats (`player.goals !== undefined`) to switch display format, but doesn't have explicit baseball handling. Baseball block stats (runs, hits, RBIs, HR) exist in the `BlockPlayerStat` type but the rendering code in `CollapsedGameFlow.tsx` only branches on basketball vs hockey. Baseball games will fall through to the basketball formatting path, showing "pts" for baseball players. This is a frontend bug, but it's caused by the backend not signaling sport type clearly enough at the block level.

### Where the backend is leaking old assumptions

- **The `moments` layer is vestigial for consumers.** The API returns both `moments` (inside `flow.moments`) and `blocks`. The frontend's primary view uses blocks exclusively. Moments exist as a fallback when blocks are absent, but in the consumer experience they serve no purpose if blocks exist.

  > **Resolved in `aidlc_1`:** The `/api/v1/` consumer endpoint exposes blocks only. Moments are not included in the consumer response. They remain as an internal pipeline artifact for traceability.

- **`story_version = "v2-moments"` naming.** The DB filter for current flows was `v2-moments` but the actual consumer output is blocks, not moments. This naming was confusing.

  > **Resolved in `aidlc_1`:** New pipeline runs write `story_version = "v2-blocks"`. Legacy rows carrying `"v2-moments"` are accepted on read during the transition window and upgraded on re-run. See `docs/gameflow/version-semantics.md`.

- **Scores are tuples, not objects.** `scoreBefore` and `scoreAfter` are `[int, int]` arrays on admin endpoints. The frontend has to know that index 0 is away and index 1 is home (after the API swap). This is a brittle contract.

  > **Partially resolved in `aidlc_1`:** The consumer endpoint (`/api/v1/`) returns `ScoreObject {home, away}`. Admin endpoints still use tuples; full migration is Phase 2.

---

## Game flow quality read

The pipeline architecture is genuinely good. 8 stages, clear separation of concerns, deterministic grouping with AI-assisted narrative generation, multi-layer validation, and graceful fallback to templates. This is not a toy.

The prompt engineering is thoughtful. The 3-layer system prompt (stable narrator identity + game-specific data + guardrail postscript) with a 2-pass rendering approach (per-block generation + game-level flow smoothing) is the right architecture. The forbidden words list, cliche detection, and anti-stat-feed rules show real attention to output quality.

**But quality is only as good as what gets through validation, and validation has gaps.**

What is strong:
- Structural validation is solid. Block count, word count, sentence count, role constraints, score continuity — these are enforced.
- Factual validation catches stat claims without supporting data and training-data bleed. This is the right instinct.
- Quality scoring with repetition, vocabulary diversity, readability, and cliche detection gives a composite score that drives PUBLISH/REGENERATE/FALLBACK decisions. The thresholds (>=70 publish, 40-69 regenerate, <40 fallback) are reasonable.
- The deterministic template fallback means a bad AI output never reaches the consumer. This is the most important quality guarantee in the system.

What is weak:
- **No regression testing across historical games.** The pipeline runs forward on new games. There is no mechanism to validate quality across a corpus of previously generated flows. If a prompt change degrades quality on comeback games, there's no way to catch that before it ships.
- **No sport-specific quality tuning.** The same quality thresholds apply to NBA and MLB games. A 7-block narrative works differently for a 150-play basketball game vs a 60-play baseball game. The quality scoring doesn't account for sport-specific expectations.
- **The quality score is heuristic-only.** Repetition, vocabulary, readability, and cliche counts are useful signals but they don't capture whether the narrative actually tells a coherent story. A narrative that scores 80 on these metrics could still be boring, misleading, or miss the most important moment of the game.
- **No late-game importance weighting.** The drama analysis stage identifies quarter weights and peak quarters, but the quality scoring doesn't check whether the RESOLUTION block actually captures the defining moment. A game-winning shot in the final seconds that gets buried in a generic "X prevailed" sentence would pass all current checks.
- **No coverage validation against key events.** There's no check that verifies: "the play that changed the game outcome is mentioned in at least one narrative block." A flow could technically pass all validation while omitting the most important play.
- **Anti-generic language checks are limited to a cliche list.** The forbidden words and cliche phrases catch the obvious patterns, but they don't detect subtler genericness like "both teams traded baskets" or "the game went back and forth" which sound specific but say nothing.
- **Regeneration is capped at 2 retries.** If the first two attempts score between 40-69, it falls back to templates. But there's no feedback loop — the regen attempt doesn't know what was wrong with the previous attempt (beyond "score was low"). Adding error context from the quality breakdown to the regen prompt would improve convergence.

---

## Viability testing read

This is the biggest gap. The pipeline has production-grade structure but no systematic viability testing framework.

What should exist but does not:

1. **Golden game corpus.** A set of 50-100 games across all sports with known "correct" narrative outputs (human-written or human-validated). Every pipeline change should be validated against this corpus. Regression testing is non-negotiable for a system that generates consumer-facing text.

2. **Coverage validation.** For every generated flow: did the narrative mention the game-winning play? Did it mention the leading scorer? Did it mention overtime if overtime happened? These are not style preferences — they are factual coverage requirements.

3. **Required event inclusion tests.** Some events must appear in the narrative: final score, winning team, any overtime. Some events should appear: largest scoring run, comeback trigger, blowout moment. The pipeline doesn't enforce this.

4. **Late-game importance weighting.** The RESOLUTION block should be tested for specificity. "Team X won 105-98" is factually correct but narratively worthless. The test should verify that the RESOLUTION block references at least one specific play from the final 2 minutes (or final inning, or final period).

5. **Deterministic fallback quality.** The template fallback exists but has it been tested for all sports? Does it produce reasonable output for overtime games? For blowouts? For games with incomplete PBP data? The fallback is the safety net — it needs its own test suite.

6. **Anti-generic scoring.** Beyond cliches, test for information density. A narrative that removes all player names and team names should be meaningfully different from a template. If it's not, the AI is adding no value.

7. **Sport-specific edge cases.** MLB perfect games, NHL shootouts, NCAAB double-overtime conference tournament games, NBA games with ejections, NFL games decided by a last-second field goal. Each of these has narrative expectations that generic block grouping may not handle well.

8. **Final vs non-final handling.** If the pipeline runs on a game that isn't final yet (possible if triggered manually), what happens? The flow should either refuse to generate or clearly mark itself as preliminary. Currently unclear.

9. **Data completeness guards.** If PBP data is incomplete (missing plays, wrong scores), the pipeline should detect this early and refuse to generate rather than producing a flow grounded in bad data. `normalize_pbp.py` does some validation but the threshold for "too incomplete to proceed" isn't well-defined.

10. **Prompt/output grading with LLM.** Use a separate LLM call (or a different model) to grade the output narrative on criteria like coherence, accuracy, engagement, and sport-appropriateness. This is the only way to get beyond heuristic quality scoring. Not cheap, but worth it for a product where narrative quality is the differentiator.

11. **Trust-preserving failure modes.** When the pipeline fails, what does the consumer see? Currently: nothing (404 on the flow endpoint). Better: a clear "Game recap not yet available" state with ETA. Even better: a minimal deterministic summary that doesn't require AI at all (score, top performers, overtime flag) as a guaranteed floor.

---

## Realtime readiness read

The backend has real-time infrastructure. WebSocket + SSE endpoints, a pub/sub manager with sequence tracking, a DB poller with configurable intervals (2s games, 1s PBP, 5s odds). The first-subscriber callback pattern is smart — only poll channels with active listeners.

**But the frontend doesn't use any of it.**

The Phase 1 frontend is entirely request-response. No WebSocket subscriptions, no SSE, no polling loops. Data is fetched on mount and on filter change. The "Resync" button triggers a POST. That's it.

This means the realtime infrastructure is currently serving zero consumer value. It exists, it works (presumably), but nobody is listening.

### What actually needs to be fresher

- **Live game scores during games.** This is the one place where real-time matters to users. If someone is watching a game and checking the app, a 60-second-old score is fine. A 5-minute-old score is bad. Current backend polling is 60s for game state + 60s for PBP. This is adequate for "near real-time" but the frontend needs to actually subscribe.
- **Live odds during games.** The live orchestrator dispatches odds polling every 15-45 seconds. The FairBet EV analysis updates accordingly. If someone is using this for live betting decisions, freshness matters. 15-second cadence is good.
- **Game flow narratives.** These are generated post-game on a scheduled batch job. Freshness doesn't matter in real-time — what matters is availability. A flow should be generated within minutes of a game going final, not the next morning at 4:30 AM. This is a latency problem, not a freshness problem.

### What can stay slow

- **Advanced stats.** Post-game enrichment. Nobody needs xGoals data within seconds of the final whistle. Daily batch is fine.
- **Social posts.** 30-minute collection cadence is fine for the current product. Social isn't load-bearing for the consumer experience.
- **Golf leaderboard.** 5-minute cadence from DataGolf is fine. Golf updates don't need sub-minute freshness.
- **Game list filters.** Static. Fetch on load. No real-time needed.

### Architectural pressure

If the frontend starts consuming WebSocket/SSE for live scores and odds:
- The in-memory pub/sub manager becomes a scaling bottleneck. Single-instance only. Would need Redis Pub/Sub or equivalent for multi-process deployment.
- The DB poller is the wrong pattern long-term. The TODO in `poller.py` says it: replace with Postgres LISTEN/NOTIFY or app-level emits from ingestion writers. Polling Postgres every 1-2 seconds is fine at current scale but wasteful at growth.
- The sequence tracking and boot epoch mechanism is well-designed for reconnection. This part is ready.

**The honest take:** Real-time should not be the next priority. The infrastructure exists and is architecturally sound enough. The priority is making sure the data that gets served (at whatever cadence) is actually correct, complete, and high quality. Real-time delivery of mediocre data is worse than slightly delayed delivery of good data.

The one exception: flow generation latency. Moving from "next morning batch" to "within 15 minutes of game final" would meaningfully improve the product without requiring WebSocket infrastructure. This is a task scheduling change, not an architecture change.

---

## Social vs sentiment read

### Current state of social

Social ingestion works but is the most fragile subsystem. Playwright-based X scraping with session cookies that expire. Rate-limited, circuit-breakered, and somewhat reliable — but operationally high-maintenance.

The data collected: team tweets scraped from official X accounts. Mapped to games by team + time window. Categorized by phase (pregame, in-game, postgame). Spoiler detection exists (score/result patterns flagged).

The frontend displays social posts in a completely decoupled section, separate from narrative blocks. Posts ordered by time, not correlated to game events. The guardrails explicitly enforce that removing all social data must not change the narrative layout.

**Is the social data actually useful?** Partially. Team tweets from official accounts are a narrow signal. They're polished, PR-approved, and rarely contain genuine reaction or insight. They're useful as "proof the game happened" and occasionally as engagement hooks (video highlights). But they don't add analytical value.

### Sentiment: is it worth pursuing?

Sentiment analysis on official team tweets is almost pointless. These accounts don't express sentiment — they announce. "FINAL: Lakers 108, Celtics 102" has no sentiment. A dunk highlight video has no analyzable sentiment beyond "this was exciting."

Where sentiment could actually be valuable:
- **Fan/public sentiment.** Aggregated reactions from general X/Twitter, Reddit, or sports forums. "How did fans feel about this game?" is an interesting product question. But scraping general social at scale is a different technical problem than scraping 30 team accounts.
- **Media sentiment.** Beat writer reactions, national columnist takes. These carry signal about narrative importance. But they require source curation, not just scraping.
- **Betting market sentiment.** Line movement and sharp vs public money splits already encode market sentiment. The odds pipeline partially captures this (line history, EV analysis). This is probably more useful than social sentiment for the current product.

### My take

Sentiment is premature. The social data itself needs stabilization first:
1. Cookie-based X scraping is not sustainable. Session tokens expire, Playwright is heavy, and X's anti-scraping measures will only get more aggressive.
2. The mapping logic (tweets to games, phase assignment) needs to be guaranteed, not best-effort. Unmapped posts with null `game_phase` are useless to the frontend.
3. Embedded tweet assignment into narrative blocks needs to actually work end-to-end with valid post IDs.

If social data collection becomes reliable and the product demonstrates that users engage with social content, then adding sentiment scoring (tone detection on post text, engagement weighting, phase-aware aggregation) makes sense. But adding sentiment on top of unreliable collection is building on sand.

The `tone_detection.py` module already exists in the pipeline — it uses OpenAI for tone classification. This could be extended to social posts. But the priority should be: reliable collection > reliable mapping > reliable display > sentiment enrichment.

---

## Contract / data-model / API read

### Field naming drift

The camelCase aliasing via Pydantic is mostly consistent but has gaps. Some advanced stats fields (`pace`, `pie`, `deflections`) are missing aliases. These will come through as snake_case in the API response if accessed directly. The frontend TypeScript types expect camelCase everywhere. Silent breakage waiting to happen.

### Duplicated enum definitions

`PipelineStage` is defined in both `api/app/db/pipeline.py` (DB layer) and `api/app/services/pipeline/models.py` (service layer). Currently synced but no enforcement. One update without the other = subtle bugs.

### Nullable chaos

`GameSummary` and `GameMeta` have 30+ nullable fields. State predicates like `isLive`, `isFinal`, `isPregame` are nullable booleans — they should be computed non-nullable bools. The frontend has to defensively check for null on fields that should always have a value.

Timestamp fields (`lastScrapedAt`, `lastIngestedAt`, etc.) are all nullable. For a game that exists in the DB, at least some of these should always be populated. The distinction between "never scraped" and "scraped but timestamp lost" is unclear.

### Admin/app boundary confusion

All game endpoints live under `/api/admin/sports/`. The consumer-facing game flow endpoint (`/games/{game_id}/flow`) is in the same router as admin pipeline controls. There is no `/api/v1/` or `/api/consumer/` namespace. When this becomes a consumer-facing product, the admin endpoints and consumer endpoints need clear separation — different auth requirements, different rate limits, different response shapes.

### Score tuple convention

Scores are `[int, int]` arrays with implicit ordering (API: away first, DB: home first). This swap happens in `_swap_score()` and is applied per-endpoint. Every new endpoint that returns scores must remember to swap. This is a class of bug waiting to happen repeatedly. Switch to `{home: int, away: int}` objects or at minimum document this as a hard contract with a shared helper that all score-returning endpoints must use.

### Overloaded JSONB fields

`derivedMetrics`, `rawPayloads`, `external_ids`, `external_codes`, `raw_stats_json` — all unstructured JSONB. Some of these are debug-only (rawPayloads), some are operational (external_ids for provider mapping). None have schema validation. This is fine for now but will become a problem when multiple consumers depend on specific keys existing.

### Transport shape mismatches

The `SocialPostEntry` in the API response includes `likesCount`, `retweetsCount`, `repliesCount` — but the frontend `SocialPost` type doesn't define these fields. They're sent but ignored. Conversely, the frontend expects `mediaType` to be `"video" | "image" | null` but the backend doesn't validate this enum — it's a nullable string.

---

## Prod viability read

### What is production-worthy

- **Odds pipeline.** Multi-source ingestion, credit quota tracking, closing line capture, EV analysis, Redis caching. This could run in prod today with monitoring.
- **Game data ingestion.** Multi-sport boxscore and PBP ingestion with proper error handling, retry logic, and job tracking. The daily sweep repairs stale statuses and fills gaps. Mature.
- **Database schema and migrations.** Well-structured, properly indexed, migration-managed. Production-ready.
- **Auth and rate limiting.** Correct implementation with production validation (key length, CORS origin checks). Ready.
- **Task infrastructure.** Celery queues with routing, locks, admin hold, orphan detection, task expiry. Operationally sound.

### What only works because the operator knows the system

- **Flow generation timing.** Flows generate on a fixed daily schedule (4:30-6:30 AM per sport). If a game goes final at 10 PM, the flow won't exist until the next morning. The operator knows to manually trigger pipeline runs for important games. A consumer product can't depend on this.
- **Social cookie refresh.** Playwright X scraping requires manual session cookie updates when they expire. No health check, no alert, no auto-refresh. The operator knows to check.
- **Advanced stats for NHL/NFL.** MoneyPuck ZIP and nflverse parquet files. The operator knows these data sources and their availability patterns. No self-healing if the upstream source changes format or URL.
- **Pipeline failure recovery.** If the flow pipeline fails for a game, the operator knows to check the admin panel, inspect stage outputs, and either rerun or skip. No automated retry for pipeline failures (distinct from task-level Celery retries).

### What needs observability / guardrails

- **Flow quality monitoring.** No dashboard showing quality scores, fallback rates, or regeneration frequency across games. If prompt quality degrades, there's no way to notice without manually inspecting individual flows.
- **Social collection health.** No alert when X scraping stops working. The circuit breaker prevents cascading failures but doesn't notify anyone.
- **Odds credit consumption.** Warning at 500 remaining credits is reactive. Should alert at 80% weekly budget consumed, not at a fixed absolute number.
- **Pipeline coverage reporting.** No view showing "X% of final games from yesterday have flows." Should exist as a daily health check.

### Trust-killing failure modes

- **Incorrect scores in narratives.** If PBP data has wrong scores and the pipeline generates a flow grounded in that data, the narrative will contain incorrect scores. The factual validation stage checks that stat claims are supported by game data — but if the game data itself is wrong, the validation passes with bad data. There should be a cross-check against the authoritative final score.
- **Generic AI narratives.** If the AI produces bland, interchangeable narratives and they score above 70 on heuristic quality checks, they ship. The user reads something that could apply to any game. Trust erodes subtly.
- **Empty or broken mini box scores.** If `mini_box` isn't populated, the frontend shows nothing where stats should be. Not a crash, but a quality gap that makes the product feel incomplete.
- **Stale social embeds.** If `embedded_social_post_id` references a deleted or invalid post, the frontend shows "Social post #12345" with no content. Actively harmful to trust.

---

## What the next major backend version should actually focus on

After reviewing the full stack, here is what I think matters, in order:

### Priority 1: Flow generation reliability and quality

This is the center of gravity. The game flow is the product's differentiator. Everything else (odds, stats, social) is supporting data.

What this means concretely:
- **Move flow generation from daily batch to event-driven.** When a game transitions to FINAL, auto-dispatch flow generation with a 5-minute delay (to ensure PBP data is complete). Kill the 4:30-6:30 AM schedule for anything except backfill.
- **Build a golden game corpus.** 10 games per sport, human-validated narrative outputs. Run every pipeline change against this corpus. This is the single most impactful testing investment.
- **Add coverage validation.** Every generated flow must mention: the final score, the winning team, and any overtime. Key play coverage should be tracked even if not enforced.
- **Add LLM-based output grading.** Use a separate model call to score narratives on coherence and information density. Expensive, but this is the product.
- ~~**Align backend and frontend block count constraints.**~~ Both now use MIN_BLOCKS = 3; verified in sync (see `docs/audits/ssot-cleanup.md`).
- **Guarantee mini_box population.** Verify that the pipeline actually populates `mini_box` with cumulative stats and deltas for all sports. Add a validation check in `validate_blocks.py`.

### Priority 2: Contract hardening

- ~~**Move scores from tuples to objects.**~~ `ScoreObject {home, away}` is now the wire contract on the consumer endpoint. Remaining admin endpoints still return tuples; migrate on touch.
- **Make state predicates non-nullable.** `isLive`, `isFinal`, `isPregame` should be computed booleans, never null.
- **Fix camelCase aliasing gaps.** Audit all response schemas for missing Field aliases.
- ~~**Single PipelineStage enum.**~~ Done: `api/app/services/pipeline/models.py` is the SSOT; DB layer re-exports.
- **Define consumer vs admin API boundaries.** Consumer game flow is live at `/api/v1/`; remaining endpoints need migration. Different routers, different auth, different rate limits.
- ~~**Document score convention.**~~ `ScoreObject` is self-documenting. The `_swap_score` per-endpoint pattern is gone.

### Priority 3: Social stabilization

- **Add session health checks.** Detect when X cookies are expired or sessions are invalid before the scraping fails.
- **Guarantee phase assignment.** Every mapped social post should have a non-null `game_phase`. If phase can't be determined, mark it explicitly (e.g., "unknown" phase) rather than leaving it null.
- **Validate embedded post IDs.** Before persisting a block with `embedded_social_post_id`, verify the post exists in the DB.
- **Consider dropping Playwright.** If the X API becomes viable (or an alternative data source), switch. Playwright scraping is an operational liability.

### Priority 4: Operational observability

- **Flow generation coverage dashboard.** % of final games with flows, by sport, by day.
- **Quality score distribution.** Histogram of quality scores, fallback rate, regeneration rate.
- **Social health monitoring.** Alert on collection failures, cookie expiration, mapping success rate.
- **Odds budget tracking.** Weekly consumption curve with projections.

### Priority 5: Realtime activation (when frontend is ready)

- **Replace DB polling with LISTEN/NOTIFY or ingestion-side emits.**
- **Move pub/sub to Redis Pub/Sub for multi-process support.**
- **Wire frontend WebSocket subscription for live game scores and odds.**
- **Implement differential updates (patches, not full refetches) for live game state.**

### Not now

- **Sentiment analysis.** Premature. Social data isn't reliable enough yet. Come back after Priority 3.
- **Analytics/ML integration into consumer experience.** The model infrastructure exists but isn't load-bearing for the product. Keep it as admin/research tooling for now.
- **Real-time game flow updates during live games.** Interesting idea but the pipeline isn't designed for partial/incremental generation. Would require significant rearchitecture.

---

## Blunt take

This backend is genuinely well-built. The architecture is sound, the database schema is mature, the pipeline design is thoughtful, and the operational patterns (locks, retries, admin hold, orphan detection) show real production experience.

The weakest point is not the code — it's the gap between "the pipeline can generate flows" and "the pipeline reliably generates good flows for every game, quickly, with validation that catches the things that actually matter." The structural plumbing is done. The quality assurance and operational reliability are not.

The second weakest point is the admin/consumer boundary. Right now everything lives under admin routes. The frontend Phase 1 is built as if it's a consumer product, but the backend is still serving it through admin endpoints. This works for now but will create real confusion as the product matures.

Social is the third problem. It works when it works, but it's one X platform change away from breaking completely, and there's no fallback.

The odds pipeline is the most production-ready thing in the repo. The game flow pipeline has the most product potential. The social pipeline has the most operational risk. The analytics/ML system has the most unused potential.

---

## North star

The backend should make exactly one promise and keep it perfectly: **for every completed game, deliver a high-quality, factually grounded, sport-appropriate narrative flow within 15 minutes of the final whistle.**

Everything else — odds, social, advanced stats, sentiment, realtime — is supporting infrastructure for that promise.

If the flow is wrong, generic, or missing, nothing else matters. If the flow is consistently good, everything else becomes a nice-to-have that builds on a foundation of trust.

Build the quality system first. Then build the speed. Then build the breadth.
