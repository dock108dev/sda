/**
 * Parse a fetch Response body as JSON.
 * Surfaces HTML/plain error pages instead of swallowing parse failures (abend audit F-022).
 */
export async function readJsonResponse(res: Response): Promise<unknown> {
  const text = await res.text();
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error(`Empty response body (HTTP ${res.status})`);
  }
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    const snippet = trimmed.replace(/\s+/g, " ").slice(0, 280);
    throw new Error(`Non-JSON response (HTTP ${res.status}): ${snippet}`);
  }
}

/** Best-effort FastAPI `detail` extraction for admin UI error messages. */
export function detailFromUnknownBody(body: unknown): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const d = (body as { detail?: unknown }).detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    const parts = d
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const msg = (item as { msg?: unknown }).msg;
          return typeof msg === "string" ? msg : null;
        }
        return null;
      })
      .filter((s): s is string => s != null);
    if (parts.length) return parts.join("; ");
  }
  return undefined;
}
