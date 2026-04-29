import { describe, expect, it, vi, afterEach } from "vitest";
import { getSseBaseUrl, safeEventSource } from "./sseBase";

describe("getSseBaseUrl", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.NEXT_PUBLIC_SPORTS_API_URL;
  });

  it("uses window origin in the browser", () => {
    expect(getSseBaseUrl()).toMatch(/\/proxy$/);
  });

  it("uses NEXT_PUBLIC_SPORTS_API_URL when window is undefined", () => {
    vi.stubGlobal("window", undefined);
    process.env.NEXT_PUBLIC_SPORTS_API_URL = "https://api.example.com";
    expect(getSseBaseUrl()).toBe("https://api.example.com");
  });

  it("falls back to localhost when server-side and env unset", () => {
    vi.stubGlobal("window", undefined);
    delete process.env.NEXT_PUBLIC_SPORTS_API_URL;
    expect(getSseBaseUrl()).toBe("http://localhost:8000");
  });
});

describe("safeEventSource", () => {
  it("returns null and warns when EventSource throws", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal(
      "EventSource",
      vi.fn().mockImplementation(() => {
        throw new Error("mixed content");
      }),
    );

    expect(safeEventSource("http://insecure/page")).toBeNull();
    expect(warn).toHaveBeenCalled();

    warn.mockRestore();
    vi.unstubAllGlobals();
  });

  it("returns null when EventSource throws and console is unavailable", () => {
    vi.stubGlobal(
      "EventSource",
      vi.fn().mockImplementation(() => {
        throw new Error("boom");
      }),
    );
    vi.stubGlobal("console", undefined);

    expect(safeEventSource("x")).toBeNull();

    vi.unstubAllGlobals();
  });

  it("returns an EventSource when construction succeeds", () => {
    class OkEs {
      url: string;
      constructor(url: string) {
        this.url = url;
      }
    }
    vi.stubGlobal("EventSource", OkEs);
    const es = safeEventSource("http://localhost/x");
    expect(es).toBeInstanceOf(OkEs);
    vi.unstubAllGlobals();
  });
});
