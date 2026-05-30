/**
 * API Proxy Route
 *
 * Streams requests to the backend API with the X-API-Key header injected
 * server-side, so the browser never sees the key. The body is passed through
 * as a stream (not buffered), which is required for SSE on /v1/sse and is a
 * win for any large response.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const API_BASE =
  process.env.SPORTS_API_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_SPORTS_API_URL ||
  "http://localhost:8000";

const API_KEY = process.env.SPORTS_API_KEY;

// Headers that must not be copied across a proxy hop.
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "content-encoding",
  "content-length",
]);

async function proxyRequest(
  request: NextRequest,
  paramsPromise: Promise<{ path: string[] }>,
): Promise<Response> {
  const { path } = await paramsPromise;
  const url = new URL(request.url);
  const targetUrl = `${API_BASE.replace(/\/$/, "")}/${path.join("/")}${url.search}`;

  // Forward client headers, dropping hop-by-hop and any header we own.
  // X-Forwarded-Origin is user-controllable so we don't pass it through.
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (HOP_BY_HOP.has(lower)) return;
    if (lower === "host" || lower === "x-forwarded-origin" || lower === "x-api-key") return;
    // Browser Basic auth protects the Next.js edge only. Do not forward it to
    // FastAPI, where bearer credentials have a different meaning.
    if (lower === "authorization" && value.toLowerCase().startsWith("basic ")) return;
    headers.set(key, value);
  });
  if (API_KEY) headers.set("X-API-Key", API_KEY);

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store",
    signal: request.signal,
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl, init);
  } catch (error) {
    // Log full detail server-side; never return the internal target URL or
    // raw fetch error message to the client. Both can leak internal network
    // topology (SPORTS_API_INTERNAL_URL host/port, DNS failure modes) even
    // when the admin UI is auth-gated. See docs/audits/security-report.md.
    const cause = error instanceof Error ? error.message : String(error);
    const correlationId =
      globalThis.crypto?.randomUUID?.() ?? `proxy-${Date.now()}`;
    console.error("Proxy error:", {
      correlationId,
      method: request.method,
      target: targetUrl,
      message: cause,
    });
    return NextResponse.json(
      {
        error: "Failed to proxy request to backend",
        correlationId,
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (HOP_BY_HOP.has(lower)) return;
    // This proxy may target an internal hostname. Do not expose upstream
    // redirect targets to the browser.
    if (lower === "location") return;
    responseHeaders.set(key, value);
  });

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, context.params);
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, context.params);
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, context.params);
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, context.params);
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, context.params);
}

export async function HEAD(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, context.params);
}
