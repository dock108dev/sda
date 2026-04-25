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
    console.error("Proxy error:", error);
    return NextResponse.json(
      { error: "Failed to proxy request to backend" },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (HOP_BY_HOP.has(key.toLowerCase())) return;
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
