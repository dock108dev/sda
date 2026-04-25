/**
 * Base URL resolver for direct browser→backend connections.
 *
 * SSE (`EventSource`) and the SSE epoch-refetch fall back to direct calls
 * because Next.js's proxy doesn't stream SSE cleanly. So these requests need
 * a real URL — and crucially, one that matches the page's protocol.
 *
 * Why this exists separately from `apiBase.ts`:
 * - `apiBase.ts` returns "/proxy" for browser fetches. That's correct for
 *   normal API calls (so the Next.js proxy can inject the API key).
 * - SSE goes direct, so it needs an absolute URL. If `NEXT_PUBLIC_SPORTS_API_URL`
 *   isn't baked into the client at build time, falling back to
 *   "http://localhost:8000" produces mixed-content failures on production
 *   HTTPS pages — Firefox specifically throws "The operation is insecure"
 *   when `new EventSource("http://...")` is called from an HTTPS document.
 *
 * Same-origin default makes the page Just Work in production (Caddy routes
 * `/v1/*` to the API container) and degrades gracefully in dev.
 */

export function getSseBaseUrl(): string {
  const envBase = process.env?.NEXT_PUBLIC_SPORTS_API_URL;
  if (envBase) return envBase;

  if (typeof window !== "undefined") {
    // Same origin — protocol matches the page, no mixed-content issues.
    return window.location.origin;
  }

  // Server-side fallback (SSE is constructed in browser only, but the hook
  // module evaluates BASE_URL at import time which can run on the server).
  return "http://localhost:8000";
}

/**
 * Construct an EventSource defensively. Returns ``null`` (and logs a console
 * warning) if construction fails — typically because the URL scheme is
 * incompatible with the page's secure context. Callers should treat ``null``
 * as "SSE unavailable; data may be stale" rather than crashing the page.
 */
export function safeEventSource(url: string): EventSource | null {
  try {
    return new EventSource(url);
  } catch (err) {
    if (typeof console !== "undefined") {
      console.warn(
        "[sseBase] EventSource construction failed; SSE will be unavailable.",
        { url, error: err },
      );
    }
    return null;
  }
}
