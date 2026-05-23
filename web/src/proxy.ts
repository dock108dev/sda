import { NextRequest, NextResponse } from "next/server";

const PROTECTED_PREFIXES = [
  "/admin",
  "/proxy/api/admin",
  "/proxy/api/sports",
  "/proxy/api/social",
  "/proxy/api/fairbet",
  "/proxy/api/analytics",
  "/proxy/api/golf",
  "/proxy/v1/sse",
];

const AUTH_REALM = "sports-data-admin";

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function shouldRequireAuth(): boolean {
  const env = process.env.ENVIRONMENT || process.env.NODE_ENV || "development";
  return (
    env === "production" ||
    env === "staging" ||
    Boolean(process.env.ADMIN_PASSWORD)
  );
}

function timingSafeEqual(left: string, right: string): boolean {
  let diff = left.length ^ right.length;
  const maxLength = Math.max(left.length, right.length);

  for (let index = 0; index < maxLength; index += 1) {
    diff |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }

  return diff === 0;
}

function basicAuthPasswordMatches(
  header: string | null,
  expectedPassword: string,
): boolean {
  if (!header?.startsWith("Basic ")) return false;

  try {
    const decoded = atob(header.slice("Basic ".length));
    const separator = decoded.indexOf(":");
    if (separator < 0) return false;
    return timingSafeEqual(decoded.slice(separator + 1), expectedPassword);
  } catch {
    return false;
  }
}

function authChallenge(status = 401): NextResponse {
  return new NextResponse("Authentication required.", {
    status,
    headers: {
      "WWW-Authenticate": `Basic realm="${AUTH_REALM}", charset="UTF-8"`,
      "Cache-Control": "no-store",
    },
  });
}

export function proxy(request: NextRequest): NextResponse {
  if (!isProtectedPath(request.nextUrl.pathname) || !shouldRequireAuth()) {
    return NextResponse.next();
  }

  const adminPassword = process.env.ADMIN_PASSWORD;
  if (!adminPassword) {
    return new NextResponse("Admin authentication is not configured.", {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    });
  }

  if (
    basicAuthPasswordMatches(request.headers.get("authorization"), adminPassword)
  ) {
    return NextResponse.next();
  }

  return authChallenge();
}

export const config = {
  matcher: ["/admin/:path*", "/proxy/:path*"],
};
