import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import { handleClubRouting, proxy } from "./proxy";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRequest(
  url: string,
  host?: string,
): NextRequest {
  if (host) {
    return new NextRequest(url, { headers: { host } });
  }
  return new NextRequest(url);
}

function slug(response: NextResponse | null): string | null {
  if (response === null) return null;
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
    const res = handleClubRouting(req);
    expect(slug(res)).toBe("the-pines-gc");
    expect(res?.status).not.toBe(301);
  });

  it("sets X-Club-Slug from /clubs/<slug>/nested/path", () => {
    const req = makeRequest("http://localhost:3000/clubs/riverside-cc/dashboard");
    const res = handleClubRouting(req);
    expect(slug(res)).toBe("riverside-cc");
  });

  it("returns null (no club routing) for non-club paths", () => {
    const req = makeRequest("http://localhost:3000/admin/dashboard");
    const res = handleClubRouting(req);
    expect(res).toBeNull();
  });

  it("does not redirect /clubs/<slug> even when BASE_DOMAIN is set", () => {
    const req = makeRequest("http://localhost:3000/clubs/the-pines-gc");
    const res = handleClubRouting(req);
    expect(res?.status).not.toBe(301);
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
    const res = handleClubRouting(req);
    expect(res?.status).toBe(301);
    const location = res?.headers.get("location") ?? "";
    expect(location.replace(/\/$/, "")).toBe("https://the-pines-gc.app.example.com");
  });

  it("uses localhost as default BASE_DOMAIN for subdomain redirects", () => {
    const prev = process.env.BASE_DOMAIN;
    delete process.env.BASE_DOMAIN;
    const req = makeRequest("http://localhost/clubs/foo-bar");
    const res = handleClubRouting(req);
    expect(res?.headers.get("location")).toContain("foo-bar.localhost");
    if (prev !== undefined) process.env.BASE_DOMAIN = prev;
  });

  it("301-redirects /clubs/<slug>/path preserving trailing path", () => {
    const req = makeRequest("http://app.example.com/clubs/the-pines-gc/leaderboard");
    const res = handleClubRouting(req);
    expect(res?.status).toBe(301);
    expect(res?.headers.get("location")).toBe(
      "https://the-pines-gc.app.example.com/leaderboard",
    );
  });

  it("sets X-Club-Slug from subdomain Host header", () => {
    const req = makeRequest(
      "http://the-pines-gc.app.example.com/",
      "the-pines-gc.app.example.com",
    );
    const res = handleClubRouting(req);
    expect(slug(res)).toBe("the-pines-gc");
    expect(res?.status).not.toBe(301);
  });

  it("ignores www subdomain", () => {
    const req = makeRequest(
      "http://www.app.example.com/",
      "www.app.example.com",
    );
    const res = handleClubRouting(req);
    expect(res).toBeNull();
  });

  it("returns null for unrelated host with no club path", () => {
    const req = makeRequest(
      "http://other-domain.com/",
      "other-domain.com",
    );
    const res = handleClubRouting(req);
    expect(res).toBeNull();
  });

  it("resolves the same club as path-based for identical slug", () => {
    vi.stubEnv("SUBDOMAIN_ROUTING", "false");
    const pathReq = makeRequest("http://localhost:3000/clubs/riverside-cc");
    const pathRes = handleClubRouting(pathReq);
    const pathSlug = slug(pathRes);

    vi.stubEnv("SUBDOMAIN_ROUTING", "true");
    const subdomainReq = makeRequest(
      "http://riverside-cc.app.example.com/",
      "riverside-cc.app.example.com",
    );
    const subdomainRes = handleClubRouting(subdomainReq);
    const subdomainSlug = slug(subdomainRes);

    expect(pathSlug).toBe("riverside-cc");
    expect(subdomainSlug).toBe("riverside-cc");
    expect(pathSlug).toBe(subdomainSlug);
  });
});

// ---------------------------------------------------------------------------
// proxy() — admin Basic auth (runs after club routing)
// ---------------------------------------------------------------------------

describe("proxy() admin Basic auth", () => {
  beforeEach(() => {
    vi.stubEnv("SUBDOMAIN_ROUTING", "false");
    vi.stubEnv("BASE_DOMAIN", "localhost");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("returns 500 when ADMIN_PASSWORD is not set", async () => {
    vi.stubEnv("ADMIN_PASSWORD", "");
    const req = new NextRequest("http://localhost:3000/admin/sports");
    const res = await proxy(req);
    expect(res.status).toBe(500);
  });

  it("returns 401 when Authorization header is missing", async () => {
    vi.stubEnv("ADMIN_PASSWORD", "secret");
    const req = new NextRequest("http://localhost:3000/admin/sports");
    expect((await proxy(req)).status).toBe(401);
  });

  it("returns 401 for non-Basic authorization", async () => {
    vi.stubEnv("ADMIN_PASSWORD", "secret");
    const req = new NextRequest("http://localhost:3000/admin/sports", {
      headers: { authorization: "Bearer token" },
    });
    expect((await proxy(req)).status).toBe(401);
  });

  it("returns 401 when Basic payload omits colon", async () => {
    vi.stubEnv("ADMIN_PASSWORD", "secret");
    const encoded = Buffer.from("nocolonhere", "utf8").toString("base64");
    const req = new NextRequest("http://localhost:3000/admin/sports", {
      headers: { authorization: `Basic ${encoded}` },
    });
    expect((await proxy(req)).status).toBe(401);
  });

  it("returns 401 for wrong password", async () => {
    vi.stubEnv("ADMIN_PASSWORD", "secret");
    const encoded = Buffer.from("admin:wrongpass", "utf8").toString("base64");
    const req = new NextRequest("http://localhost:3000/admin/sports", {
      headers: { authorization: `Basic ${encoded}` },
    });
    expect((await proxy(req)).status).toBe(401);
  });

  it("returns 200 for valid admin Basic credentials", async () => {
    vi.stubEnv("ADMIN_PASSWORD", "secret");
    const encoded = Buffer.from("admin:secret", "utf8").toString("base64");
    const req = new NextRequest("http://localhost:3000/admin/sports", {
      headers: { authorization: `Basic ${encoded}` },
    });
    const res = await proxy(req);
    expect(res.status).toBe(200);
  });

  it("applies club routing before requiring admin auth", async () => {
    vi.stubEnv("ADMIN_PASSWORD", "secret");
    const req = new NextRequest("http://localhost:3000/clubs/my-club");
    const res = await proxy(req);
    expect(res.status).not.toBe(401);
    expect(slug(res)).toBe("my-club");
  });
});
