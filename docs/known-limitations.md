# Known Limitations

- Homepage game lists are intentionally spoiler-light and omit the detail payload's top-level score. Current live summaries may include `liveSnapshot.score` when live play-by-play has period and clock state.
- The scraper refreshes every five minutes, so live game data can lag by one polling interval plus API latency.
- OpenAI context copy is optional. Without `OPENAI_API_KEY`, the API returns deterministic local context sentences.
- Historical modules may remain in the repository for schema and migration
  compatibility. Production relevance is defined by mounted API routers,
  scheduled Celery tasks, and compose services, not by file presence.
- CI still runs broad historical checks; CI coverage is larger than the active catch-up runtime boundary.
- Odds, golf, social scraping, analytics, simulator, billing, auth product
  routes, and product realtime streams are not supported by the current
  scheduled runtime.
- `/api/social/*` is mounted for manual social post/account data access, but no
  social collection worker is scheduled.
- `/api/admin/realtime/test-emit` is available only outside production/staging
  for load-test event injection; realtime subscribe/stream product routes are
  not mounted.
