import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSseBaseUrl, safeEventSource } from "./sseBase";

describe("getSseBaseUrl", () => {
  const originalEnv = process.env.NEXT_PUBLIC_SPORTS_API_URL;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.NEXT_PUBLIC_SPORTS_API_URL;
    } else {
      process.env.NEXT_PUBLIC_SPORTS_API_URL = originalEnv;
    }
  });

  it("returns NEXT_PUBLIC_SPORTS_API_URL when set", () => {
    process.env.NEXT_PUBLIC_SPORTS_API_URL = "https://api.example.com";
    expect(getSseBaseUrl()).toBe("https://api.example.com");
  });

  it("falls back to window.location.origin in browser when env is unset", () => {
    delete process.env.NEXT_PUBLIC_SPORTS_API_URL;
    // jsdom default is http://localhost:3000
    expect(getSseBaseUrl()).toBe(window.location.origin);
  });
});

describe("safeEventSource", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
  });

  afterEach(() => {
    globalThis.EventSource = originalEventSource;
    vi.restoreAllMocks();
  });

  it("returns the EventSource on successful construction", () => {
    class GoodES {
      constructor(public url: string) {}
    }
    // @ts-expect-error -- test stub
    globalThis.EventSource = GoodES;
    const result = safeEventSource("https://example.com/sse");
    expect(result).toBeInstanceOf(GoodES);
  });

  it("returns null and logs a warning when construction throws", () => {
    class BadES {
      constructor(_url: string) {
        throw new DOMException("The operation is insecure.", "SecurityError");
      }
    }
    // @ts-expect-error -- test stub
    globalThis.EventSource = BadES;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = safeEventSource("http://example.com/sse");
    expect(result).toBeNull();
    expect(warn).toHaveBeenCalled();
  });
});
