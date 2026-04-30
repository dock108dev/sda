import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("next.config.ts CSP baseline", () => {
  it("includes hardened directives aligned with security review", () => {
    const configPath = join(__dirname, "..", "next.config.ts");
    const src = readFileSync(configPath, "utf8");
    expect(src).toContain("base-uri 'self'");
    expect(src).toContain("object-src 'none'");
    expect(src).toContain("form-action 'self'");
  });
});
