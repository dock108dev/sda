import type { NextConfig } from "next";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-XSS-Protection", value: "1; mode=block" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      // Next.js requires unsafe-inline for its runtime styles; tighten with nonces once on Next 14+
      "style-src 'self' 'unsafe-inline'",
      // Twitter embed widget
      "script-src 'self' 'unsafe-inline' https://platform.twitter.com",
      "frame-src https://platform.twitter.com",
      "img-src 'self' data: https:",
      "connect-src 'self'",
      "font-src 'self'",
    ].join("; "),
  },
];

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@dock108/ui", "@dock108/ui-kit", "@dock108/js-core"],
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;

