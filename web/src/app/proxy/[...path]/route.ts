/**
 * API Proxy Route
 *
 * Proxies requests to the backend API with the API key header.
 * This allows client components to make authenticated API requests
 * without exposing the API key to the browser.
 */

import { NextRequest, NextResponse } from "next/server";
import http from "http";
import https from "https";

const API_BASE =
  process.env.SPORTS_API_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_SPORTS_API_URL ||
  "http://localhost:8000";

const API_KEY = process.env.SPORTS_API_KEY;

async function proxyRequest(
  request: NextRequest,
  params: Promise<{ path: string[] }>
): Promise<NextResponse> {
  const { path } = await params;
  const pathStr = path.join("/");
  const url = new URL(request.url);
  const targetPath = `/${pathStr}${url.search}`;

  // Parse the API base URL
  const apiUrl = new URL(API_BASE);
  const isHttps = apiUrl.protocol === "https:";
  const httpModule = isHttps ? https : http;
  const defaultPort = isHttps ? 443 : 80;

  // Get request body
  let body: string | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    body = await request.text();
  }

  return new Promise((resolve) => {
    // Only forward headers that the backend needs; do NOT forward
    // X-Forwarded-Origin (user-controllable) to prevent origin-spoofing.
    const incomingOrigin =
      request.headers.get("origin") || new URL(request.url).origin;
    const incomingAuth = request.headers.get("authorization") || undefined;

    const options: http.RequestOptions = {
      hostname: apiUrl.hostname,
      port: apiUrl.port || defaultPort,
      path: targetPath,
      method: request.method,
      headers: {
        "Content-Type": request.headers.get("content-type") || "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        ...(incomingOrigin ? { Origin: incomingOrigin } : {}),
        ...(incomingAuth ? { Authorization: incomingAuth } : {}),
        ...(body ? { "Content-Length": Buffer.byteLength(body) } : {}),
      },
    };

    const req = httpModule.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => {
        data += chunk;
      });
      res.on("end", () => {
        resolve(
          new NextResponse(data, {
            status: res.statusCode || 500,
            headers: {
              "Content-Type": res.headers["content-type"] || "application/json",
            },
          })
        );
      });
    });

    req.on("error", (error) => {
      console.error("Proxy error:", error);
      resolve(
        NextResponse.json(
          { error: "Failed to proxy request to backend" },
          { status: 502 }
        )
      );
    });

    if (body) {
      req.write(body);
    }
    req.end();
  });
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  return proxyRequest(request, context.params);
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  return proxyRequest(request, context.params);
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  return proxyRequest(request, context.params);
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  return proxyRequest(request, context.params);
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  return proxyRequest(request, context.params);
}
