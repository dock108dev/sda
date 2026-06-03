# Known Limitations

- Homepage game lists are compact summaries. The normalized detail card feed is
  the source for score, player stats, team stats, and box-score data.
- The scraper refreshes every five minutes, so live game data can lag by one polling interval plus API latency.
- OpenAI context copy is optional. Without `OPENAI_API_KEY`, the API returns deterministic local context sentences.
- Production relevance is defined by mounted API routers, scheduled Celery
  tasks, and compose services.
- CI still runs broad historical checks; CI coverage is larger than the active catch-up runtime boundary.
- Odds, golf, social scraping, analytics, simulator, auth product,
  onboarding, club-management, and product realtime streams are not supported
  by the current mounted/scheduled runtime.
- NFL is currently schedule-stub only in the active beat scheduler; live PBP and
  box-score polling are not part of `poll_live_pbp`.
- `/api/social/*` is mounted for manual social post/account data access, but no
  social collection worker is scheduled.
- `/api/admin/realtime/test-emit` is available only outside production/staging
  for load-test event injection; realtime subscribe/stream product routes are
  not mounted.
- Transactional email supports SMTP and SES. `RESEND_API_KEY` is not consumed by
  the current API service.
