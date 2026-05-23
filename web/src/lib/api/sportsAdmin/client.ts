/**
 * API client for sports admin endpoints.
 *
 * Handles both browser and server-side (SSR) requests. In Docker environments,
 * server-side requests use SPORTS_API_INTERNAL_URL to reach the API container
 * directly, while browser requests use NEXT_PUBLIC_SPORTS_API_URL.
 */

import { getApiBase } from "../apiBase";

/**
 * Strip API-key / bearer-token shapes from a string before it enters an
 * Error.message. The upstream API should never echo our X-API-Key back, but
 * a misconfigured upstream proxy could surface it via a debug page; this
 * keeps the secret out of logs and any client-visible surface.
 */
function redactSensitive(s: string): string {
  return s
    .replace(/(x-api-key\s*[:=]\s*)["']?[^"'\s,;]+/gi, "$1[redacted]")
    .replace(/(authorization\s*[:=]\s*)["']?(?:bearer\s+)?[^"'\s,;]+/gi, "$1[redacted]")
    .replace(/("?(?:api[_-]?key|access[_-]?token|secret)"?\s*[:=]\s*)"?[^"\s,}]+/gi, "$1[redacted]");
}

/**
 * Typed error carrying the upstream HTTP status. Callers should use
 * `err instanceof HttpError && err.status === 404` rather than
 * string-matching on the message, which is brittle to message-format changes.
 * See docs/audits/error-handling-report.md AH-24.
 */
export class HttpError extends Error {
  readonly status: number;
  readonly body: string;
  constructor(status: number, body: string) {
    // Cap body in Error.message: upstream error pages may include long HTML
    // / stack traces which would balloon server logs and risk surfacing
    // internal details if the message is ever shown to a client. Full body
    // remains on `.body` for callers that knowingly need it.
    const safe = redactSensitive(body);
    const snippet = safe.length > 500 ? `${safe.slice(0, 500)}…` : safe;
    super(`Request failed (${status}): ${snippet}`);
    this.name = "HttpError";
    this.status = status;
    this.body = redactSensitive(body);
  }
}

/** Build headers including API key if configured. */
function buildHeaders(init?: RequestInit): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> ?? {}),
  };

  // Add API key for authentication (server-side only, not exposed to browser)
  const apiKey = process.env.SPORTS_API_KEY;
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }

  return headers;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const apiBase = getApiBase({
    serverInternalBaseEnv: process.env.SPORTS_API_INTERNAL_URL,
    serverPublicBaseEnv: process.env.NEXT_PUBLIC_SPORTS_API_URL,
    localhostPort: 8000,
  });
  const url = `${apiBase}${path}`;

  try {
    const res = await fetch(url, {
      ...init,
      headers: buildHeaders(init),
      cache: "no-store",
    });

    if (!res.ok) {
      // Bound upstream error body in memory so a hostile or misconfigured
      // upstream can't stream a large payload on the error path.
      const raw = await res.text();
      const body = raw.length > 2048 ? raw.slice(0, 2048) : raw;
      throw new HttpError(res.status, body);
    }

    return await res.json();
  } catch (err) {
    if (err instanceof TypeError && err.message.includes("fetch")) {
      // Don't include `apiBase` in the surfaced error: it may be the
      // internal SPORTS_API_INTERNAL_URL (Docker hostname / port) which we
      // don't want appearing in client-side error overlays or RSC HTML.
      throw new Error("Failed to connect to backend. Is the server running?");
    }
    throw err;
  }
}
