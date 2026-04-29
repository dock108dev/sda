import { describe, expect, it, vi, afterEach } from "vitest";
import { getApiBase } from "./apiBase";

describe("getApiBase", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns /proxy in the browser", () => {
    expect(getApiBase()).toBe("/proxy");
  });

  it("prefers internal server base when window is undefined", () => {
    vi.stubGlobal("window", undefined);
    expect(getApiBase({ serverInternalBaseEnv: "http://api:8000" })).toBe("http://api:8000");
  });

  it("falls back to public server base then localhost", () => {
    vi.stubGlobal("window", undefined);
    expect(getApiBase({ serverPublicBaseEnv: "http://host.docker.internal:8000" })).toBe(
      "http://host.docker.internal:8000",
    );
    expect(getApiBase()).toBe("http://localhost:8000");
  });
});
