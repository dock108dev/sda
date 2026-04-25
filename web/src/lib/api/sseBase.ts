/**
 * Base URL resolver for SSE (`EventSource`) connections.
 *
 * SSE goes through the Next.js `/proxy` path so the X-API-Key header is
 * injected server-side. `EventSource` cannot send custom headers, so a direct
 * browser → FastAPI connection 401s in production. The proxy route streams
 * the response body intact, which works for SSE.
 *
 * In the browser we always use same-origin `/proxy` to avoid mixed-content
 * issues and to keep the API key out of the client bundle.
 */

export function getSseBaseUrl(): string {
  if (typeof window !== "undefined") {
    return `${window.location.origin}/proxy`;
  }

  // Server-side fallback (SSE is constructed in the browser only, but the
  // hook module evaluates this at import time which can run on the server).
  const envBase = process.env?.NEXT_PUBLIC_SPORTS_API_URL;
  if (envBase) return envBase;
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
