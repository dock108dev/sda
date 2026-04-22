import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import { middleware } from "./middleware";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRequest(
  url: string,
  host?: string,
): NextRequest {
  const req = new NextRequest(url);
  if (host) {
    // NextRequest headers are read-only on the real object; override via init
    return new NextRequest(url, {
      headers: host ? { host } : undefined,
    });
  }
  return req;
}

function slug(response: NextResponse): string | null {
  // The forwarded slug header is set on the rewritten request, not the response.
  // In tests we check the response's "x-middleware-request-x-club-slug" header
  // which Next.js propagates internally, OR we inspect the request object returned.
  // Since we control middleware, we directly call it and read its output.
  return response.headers.get("x-middleware-request-x-club-slug");
}

// ---------------------------------------------------------------------------
// Path-based mode (SUBDOMAIN_ROUTING=false, default)
// ---------------------------------------------------------------------------

describe("path-based routing (SUBDOMAIN_ROUTING=false)", () => {
  beforeEach(() => {
    vi.stubEnv("SUBDOMAIN_ROUTING", "false");
    vi.stubEnv("BASE_DOMAIN", "app.example.com");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("sets X-Club-Slug from /clubs/<slug>", () => {
    const req = makeRequest("http://localhost:3000/clubs/the-pines-gc");
    const res = middleware(req);
    expect(slug(res)).toBe("the-pines-gc");
    expect(res.status).not.toBe(301);
  });

  it("sets X-Club-Slug from /clubs/<slug>/nested/path", () => {
    const req = makeRequest("http://localhost:3000/clubs/riverside-cc/dashboard");
    const res = middleware(req);
    expect(slug(res)).toBe("riverside-cc");
  });

  it("does not set X-Club-Slug for non-club paths", () => {
    const req = makeRequest("http://localhost:3000/admin/dashboard");
    const res = middleware(req);
    expect(slug(res)).toBeNull();
    expect(res.status).not.toBe(301);
  });

  it("does not redirect /clubs/<slug> even when BASE_DOMAIN is set", () => {
    const req = makeRequest("http://localhost:3000/clubs/the-pines-gc");
    const res = middleware(req);
    expect(res.status).not.toBe(301);
  });
});

// ---------------------------------------------------------------------------
// Subdomain routing mode (SUBDOMAIN_ROUTING=true)
// ---------------------------------------------------------------------------

describe("subdomain routing (SUBDOMAIN_ROUTING=true)", () => {
  beforeEach(() => {
    vi.stubEnv("SUBDOMAIN_ROUTING", "true");
    vi.stubEnv("BASE_DOMAIN", "app.example.com");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("301-redirects /clubs/<slug> to subdomain URL", () => {
    const req = makeRequest("http://app.example.com/clubs/the-pines-gc");
    const res = middleware(req);
    expect(res.status).toBe(301);
    // NextResponse.redirect normalises bare origins to include a trailing slash
    const location = res.headers.get("location") ?? "";
    expect(location.replace(/\/$/, "")).toBe("https://the-pines-gc.app.example.com");
  });

  it("301-redirects /clubs/<slug>/path preserving trailing path", () => {
    const req = makeRequest("http://app.example.com/clubs/the-pines-gc/leaderboard");
    const res = middleware(req);
    expect(res.status).toBe(301);
    expect(res.headers.get("location")).toBe(
      "https://the-pines-gc.app.example.com/leaderboard",
    );
  });

  it("sets X-Club-Slug from subdomain Host header", () => {
    const req = makeRequest(
      "http://the-pines-gc.app.example.com/",
      "the-pines-gc.app.example.com",
    );
    const res = middleware(req);
    expect(slug(res)).toBe("the-pines-gc");
    expect(res.status).not.toBe(301);
  });

  it("ignores www subdomain", () => {
    const req = makeRequest(
      "http://www.app.example.com/",
      "www.app.example.com",
    );
    const res = middleware(req);
    expect(slug(res)).toBeNull();
    expect(res.status).not.toBe(301);
  });

  it("does not set X-Club-Slug for unrelated host", () => {
    const req = makeRequest(
      "http://other-domain.com/",
      "other-domain.com",
    );
    const res = middleware(req);
    expect(slug(res)).toBeNull();
    expect(res.status).not.toBe(301);
  });

  it("resolves the same club as path-based for identical slug", () => {
    vi.stubEnv("SUBDOMAIN_ROUTING", "false");
    const pathReq = makeRequest("http://localhost:3000/clubs/riverside-cc");
    const pathRes = middleware(pathReq);
    const pathSlug = slug(pathRes);

    vi.stubEnv("SUBDOMAIN_ROUTING", "true");
    const subdomainReq = makeRequest(
      "http://riverside-cc.app.example.com/",
      "riverside-cc.app.example.com",
    );
    const subdomainRes = middleware(subdomainReq);
    const subdomainSlug = slug(subdomainRes);

    expect(pathSlug).toBe("riverside-cc");
    expect(subdomainSlug).toBe("riverside-cc");
    expect(pathSlug).toBe(subdomainSlug);
  });
});
