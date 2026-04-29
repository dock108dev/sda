import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@dock108/js-core": path.resolve(__dirname, "../packages/js-core/src/index.ts"),
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: [],
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary", "json-summary", "html"],
      reportsDirectory: "./coverage",
      // Thresholds apply only to these paths (shared utils/hooks/API helpers; App Router pages excluded).
      include: [
        "src/lib/utils/**/*.{ts,tsx}",
        "src/lib/constants/**/*.{ts,tsx}",
        "src/lib/hooks/**/*.ts",
        "src/lib/api/sseBase.ts",
        "src/lib/api/apiBase.ts",
        "src/proxy.ts",
      ],
      exclude: [
        "**/*.d.ts",
        "**/*.config.*",
        "**/ci-smoke.test.ts",
        "**/*.{test,spec}.{ts,tsx}",
        // SSE reconnect hooks are branch-heavy (timers, EventSource, backoff); covered by dedicated tests but omitted from % gates.
        "src/lib/hooks/useLiveGameScore.ts",
        "src/lib/hooks/useLiveOdds.ts",
      ],
      thresholds: {
        lines: 90,
        functions: 90,
        branches: 90,
        statements: 90,
      },
    },
  },
});
