# Known Limitations

- Homepage game lists are intentionally spoiler-light and omit the detail payload's top-level score. Current live summaries may include `liveSnapshot.score` when live play-by-play has period and clock state.
- The scraper refreshes every five minutes, so live game data can lag by one polling interval plus API latency.
- OpenAI context copy is optional. Without `OPENAI_API_KEY`, the API returns deterministic local context sentences.
- Historical legacy modules may remain in the repository for schema and migration compatibility, but they are not mounted, scheduled, or composed by the active service.
- CI still runs broad historical checks; CI coverage is larger than the active catch-up runtime boundary.
- Odds, golf, social scraping, analytics, simulator, billing, auth product routes, and realtime streams are not supported by the current runtime.
