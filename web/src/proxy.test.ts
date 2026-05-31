import { Buffer } from "node:buffer";

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { proxy } from "./proxy";

function request(path: string, authorization?: string): NextRequest {
  return new NextRequest(`https://sda.example.test${path}`, {
    headers: authorization ? { authorization } : undefined,
  });
}

function basic(password: string): string {
  return `Basic ${Buffer.from(`admin:${password}`).toString("base64")}`;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("admin proxy gate", () => {
  it("requires basic auth on every proxy path in production", () => {
    vi.stubEnv("ENVIRONMENT", "production");
    vi.stubEnv("ADMIN_PASSWORD", "correct-password");

    const response = proxy(request("/proxy/api/v1/games/123"));

    expect(response.status).toBe(401);
  });

  it("requires basic auth on admin pages in production", () => {
    vi.stubEnv("ENVIRONMENT", "production");
    vi.stubEnv("ADMIN_PASSWORD", "correct-password");

    const response = proxy(request("/admin"));

    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toContain("Basic");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("requires basic auth on privileged proxy paths", () => {
    vi.stubEnv("ENVIRONMENT", "production");
    vi.stubEnv("ADMIN_PASSWORD", "correct-password");

    const response = proxy(request("/proxy/api/admin/pipeline/run"));

    expect(response.status).toBe(401);
  });

  it("requires auth when only NODE_ENV is production", () => {
    vi.stubEnv("ENVIRONMENT", "");
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ADMIN_PASSWORD", "correct-password");

    const response = proxy(request("/admin"));

    expect(response.status).toBe(401);
  });

  it("allows the request when the configured password matches", () => {
    vi.stubEnv("ENVIRONMENT", "production");
    vi.stubEnv("ADMIN_PASSWORD", "correct-password");

    const response = proxy(
      request("/proxy/api/admin/pipeline/run", basic("correct-password")),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("rejects malformed basic auth credentials", () => {
    vi.stubEnv("ENVIRONMENT", "production");
    vi.stubEnv("ADMIN_PASSWORD", "correct-password");

    expect(proxy(request("/admin", "Basic !!!")).status).toBe(401);
    expect(proxy(request("/admin", `Basic ${Buffer.from("admin").toString("base64")}`)).status).toBe(
      401,
    );
  });

  it("fails closed in production when admin auth is not configured", async () => {
    vi.stubEnv("ENVIRONMENT", "production");
    vi.stubEnv("ADMIN_PASSWORD", "");

    const response = proxy(request("/admin"));

    expect(response.status).toBe(503);
    expect(await response.text()).toContain("not configured");
  });

  it("does not require local development auth unless a password is configured", () => {
    vi.stubEnv("ENVIRONMENT", "development");
    vi.stubEnv("ADMIN_PASSWORD", "");

    const response = proxy(request("/admin"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
