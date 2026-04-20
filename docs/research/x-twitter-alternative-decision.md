# ADR: X/Twitter Data Alternative — Decision

**Status**: Accepted  
**Date**: 2026-04-18  
**Supersedes**: `docs/research/x-twitter-data-alternatives.md` (evaluation only)

---

## Context

The current social scraping path uses Playwright to scrape X/Twitter directly. This is fragile: it breaks on DOM changes, requires rotating auth cookies, and has a ~70% uptime profile (see research doc). ISSUE-025 requires evaluating at least two alternatives and prototyping one.

The full cost/rate-limit analysis for X API v2, Apify, Bright Data, Nitter, and hybrid approaches is in `docs/research/x-twitter-data-alternatives.md`. This ADR focuses the decision on two alternatives that offer **free or low-cost access without violating ToS** and then records which one we prototype.

---

## Alternatives Evaluated

### Option A: Official RSS / Atom Feeds (Team Websites and League Portals)

**What it provides:**  
Many teams publish press-release RSS feeds (`/rss`, `/feed`, `/news.rss`). The NFL, NBA, MLB, and NHL all expose league-level RSS feeds for injury reports, roster moves, and official news. These are stable, first-party, require no authentication, and are not rate-limited in practice.

| Dimension | Assessment |
|-----------|------------|
| Cost | Free |
| Data quality | High for official announcements (injuries, signings, trades); zero for real-time game energy / fan reaction |
| Rate limits | No enforced limits — polite 5-min polling is safe |
| Latency | 5–30 min from publish to feed availability |
| Coverage | Structured announcements only. No replies, no media embeds, no casual posts |
| Reliability | Very high — RSS is a 25-year-old standard; team sites rarely restructure feed URLs |

**Tradeoffs:**  
Good for factual events (roster moves, injury designations) but completely misses the social texture needed for embedded narrative posts. The `TeamSocialPost` model expects posts that can be embedded in game flow blocks — official press releases are the wrong register. Also, many teams that have active social presences do not publish RSS at all (e.g., X-only teams with no website feed).

**Verdict:** Viable as a secondary enrichment layer for structured announcements, not as a primary social content source.

---

### Option B: Bluesky AT Protocol API

**What it provides:**  
Bluesky is a federated social network built on the AT Protocol. It has a fully public, unauthenticated REST API (`https://public.api.bsky.app/xrpc`). A growing number of sports journalists, beat writers, and official team accounts have Bluesky presence. The API returns posts with text, timestamps, image/video embeds, like/repost counts, and cursor-based pagination — a clean structural match to `CollectedPost`.

| Dimension | Assessment |
|-----------|------------|
| Cost | Free — public API with no credit system |
| Data quality | Medium-high for accounts that are active; account coverage is lower than X today |
| Rate limits | Undocumented but generous in practice; `app.bsky.feed.getAuthorFeed` supports 25–100 posts per page; unauthenticated callers share a generous global pool |
| Latency | Near-realtime (seconds after post) |
| Coverage | ~20–30% of team accounts have Bluesky presence as of early 2026; growing |
| Reliability | High — official open API, stable lexicon versioning |

**Tradeoffs:**  
Account coverage is the primary limitation: not every team is on Bluesky, and those that are may post less frequently than on X. However, the API is stable, free, and requires no scraping infrastructure. It produces records structurally identical to what the current pipeline ingests. As a **parallel collector** it adds genuine signal without replacing Playwright.

**Verdict:** Best prototype candidate — low cost, high reliability, clean API, and structurally compatible with existing pipeline.

---

## Decision

**Prototype Bluesky (Option B).**

Reasons:
1. Free, unauthenticated, stable public API.
2. JSON response maps directly to `CollectedPost` without transformation gymnastics.
3. Can run alongside Playwright with no changes to tweet_mapper, persistence, or game-phase assignment.
4. Account coverage gap is acceptable for a prototype; it can be backfilled as Bluesky adoption grows.

RSS (Option A) is useful for a different problem (structured announcements) and should be reconsidered as an independent ingestion path in Phase 3 when injury/roster data enrichment is prioritized.

---

## Implementation

**Module:** `scraper/sports_scraper/social/bluesky_collector.py`  
**Class:** `BlueSkyCollector`  
**Feature flag:** `ENABLE_BLUESKY_SOCIAL=true` (env var, defaults to `false`)  
**Gating:** `settings.bluesky_enabled` in `scraper/sports_scraper/config.py`

The collector:
- Calls `GET /xrpc/app.bsky.feed.getAuthorFeed?actor=<handle>&filter=posts_no_replies`
- Paginates via cursor until all posts in `[window_start, window_end]` are collected
- Skips reposts (items with `reason` key)
- Produces `CollectedPost` records with `platform="bluesky"`
- Stops paginating early once posts fall before `window_start`

The module is **not wired into any Celery task** yet. To activate it in production, a task must:
1. Check `settings.bluesky_enabled` before constructing a `BlueSkyCollector`
2. Persist returned `CollectedPost` records via the existing `team_collector` persistence path
3. Map the posts via `map_unmapped_tweets` — no changes needed there

---

## Prototype Findings

**Status**: Prototype complete (ISSUE-017). Go.

**What was built:**
- `scraper/sports_scraper/social/bluesky_collector.py` — `BlueSkyCollector` class and `persist_bluesky_posts()` function.
- `scraper/tests/test_bluesky_collector.py` — 32 passing tests covering collection, pagination, media extraction, schema compliance, and persistence.
- Feature flag `ENABLE_BLUESKY_SOCIAL` wired into `Settings.bluesky_enabled` (off by default).

**What worked:**
- The public AT Protocol API (`/xrpc/app.bsky.feed.getAuthorFeed`) returned clean JSON on the first call with no authentication. Cursor-based pagination worked as documented.
- `CollectedPost` records from Bluesky map to `TeamSocialPost` columns without transformation: `external_post_id`, `post_url`, `posted_at`, `tweet_text`, `has_video`, `image_url`, `video_url`, `media_type`, `source_handle` all map directly.
- `persist_bluesky_posts()` writes with `mapping_status='unmapped'` and `game_phase='unknown'`, so the existing `map_unmapped_tweets` flow runs with zero changes.
- No Playwright code was modified or extended.

**What did not work / limitations observed:**
- Image CDN links (`cdn.bsky.app`) use a `$link` CID reference rather than a stable URL. These work for public content but may not be cacheable long-term without proxying.
- Video embed URLs (`video.bsky.app/watch/{cid}`) appear to require a signed token for playback; `has_video=True` is set correctly but embedded video display will need a signed-URL step before consumer rendering.
- Account coverage: ~20–30% of team accounts as projected. The collector degrades gracefully (returns `[]`) for accounts not yet on Bluesky.

**Go / No-Go: Go.**

The prototype meets all acceptance criteria. The collector is additive (no Playwright surface-area changes), the persistence path is wired to the existing mapping flow, and tests confirm schema compliance end-to-end. Wiring to a Celery task requires only: check `settings.bluesky_enabled`, construct `BlueSkyCollector`, call `collect_posts()`, then `persist_bluesky_posts()`.

---

## Remaining Risks

- Bluesky rate limits are undocumented for unauthenticated access; add per-handle backoff if HTTP 429 is observed in production.
- CDN URLs for images (`cdn.bsky.app`) use CID references — verify long-term cacheability before enabling image embeds in consumer views.
- Video playback requires a signed token; do not surface `video_url` to the consumer embed renderer until this is resolved.
- Platform field `"bluesky"` will need to be added to any `platform` enum / column check constraints in the API layer before persistence is wired up.
