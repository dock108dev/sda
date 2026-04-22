import { NextRequest, NextResponse } from "next/server";

const CLUB_PATH_RE = /^\/clubs\/([a-z0-9-]+)(\/.*)?$/;
const SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;

function extractSubdomainSlug(host: string, baseDomain: string): string | null {
  const suffix = `.${baseDomain}`;
  if (!host.endsWith(suffix)) return null;
  const slug = host.slice(0, -suffix.length);
  if (!slug || slug === "www" || !SLUG_RE.test(slug)) return null;
  return slug;
}

/**
 * Resolves club context from the incoming request. Public — no auth required.
 *
 * Path-based mode (SUBDOMAIN_ROUTING=false, default):
 *   /clubs/<slug>/** → sets X-Club-Slug header and continues.
 *
 * Subdomain mode (SUBDOMAIN_ROUTING=true):
 *   /clubs/<slug>/** → 301 redirect to https://<slug>.<BASE_DOMAIN>/<rest>.
 *   <slug>.<BASE_DOMAIN>/** → sets X-Club-Slug header and continues.
 *
 * Returns `null` when the request is not a club URL — the caller continues
 * to admin-auth enforcement.
 */
export function handleClubRouting(request: NextRequest): NextResponse | null {
  const subdomainRouting = process.env.SUBDOMAIN_ROUTING === "true";
  const baseDomain = process.env.BASE_DOMAIN ?? "localhost";
  const pathname = request.nextUrl.pathname;

  if (subdomainRouting) {
    const pathMatch = CLUB_PATH_RE.exec(pathname);
    if (pathMatch) {
      const slug = pathMatch[1];
      const rest = pathMatch[2] ?? "";
      return NextResponse.redirect(
        `https://${slug}.${baseDomain}${rest}`,
        301,
      );
    }

    const host = (request.headers.get("host") ?? "").split(":")[0];
    const slug = extractSubdomainSlug(host, baseDomain);
    if (slug) {
      const requestHeaders = new Headers(request.headers);
      requestHeaders.set("x-club-slug", slug);
      return NextResponse.next({ request: { headers: requestHeaders } });
    }
    return null;
  }

  const pathMatch = CLUB_PATH_RE.exec(pathname);
  if (pathMatch) {
    const requestHeaders = new Headers(request.headers);
    requestHeaders.set("x-club-slug", pathMatch[1]);
    return NextResponse.next({ request: { headers: requestHeaders } });
  }

  return null;
}

/**
 * Constant-time string comparison to prevent timing attacks.
 * Uses Web Crypto API's subtle.digest which is available in Edge Runtime.
 */
async function timingSafeCompare(a: string, b: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const aBuffer = encoder.encode(a);
  const bBuffer = encoder.encode(b);

  const [aHash, bHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", aBuffer),
    crypto.subtle.digest("SHA-256", bBuffer),
  ]);

  const aArray = new Uint8Array(aHash);
  const bArray = new Uint8Array(bHash);

  let result = 0;
  for (let i = 0; i < aArray.length; i++) {
    result |= aArray[i] ^ bArray[i];
  }

  return result === 0;
}

/**
 * Basic auth for admin console — enforced in ALL environments.
 *
 * Requires ADMIN_PASSWORD env var. If not set, access is blocked
 * with a 500 to prevent accidental unauthenticated exposure.
 *
 * Public club routes (`/clubs/<slug>/**` and club-subdomain hosts) are
 * handled by `handleClubRouting` first and bypass this auth wall.
 */
export async function proxy(request: NextRequest) {
  const clubResponse = handleClubRouting(request);
  if (clubResponse) return clubResponse;

  const adminPassword = process.env.ADMIN_PASSWORD;

  if (!adminPassword) {
    return new NextResponse("Server misconfigured: ADMIN_PASSWORD not set", {
      status: 500,
    });
  }

  const authHeader = request.headers.get("authorization");
  if (!authHeader) return unauthorizedResponse();

  const [scheme, encoded] = authHeader.split(" ");
  if (scheme !== "Basic" || !encoded) return unauthorizedResponse();

  const decoded = Buffer.from(encoded, "base64").toString("utf-8");

  const colonIndex = decoded.indexOf(":");
  if (colonIndex === -1) return unauthorizedResponse();
  const username = decoded.substring(0, colonIndex);
  const password = decoded.substring(colonIndex + 1);

  const usernameMatch = username === "admin";
  const passwordMatch = await timingSafeCompare(password, adminPassword);

  if (usernameMatch && passwordMatch) {
    return NextResponse.next();
  }

  return unauthorizedResponse();
}

function unauthorizedResponse(): NextResponse {
  return new NextResponse("Authentication required", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Sports Admin"',
    },
  });
}

// Apply to admin UI pages only. Exempt backend-bound paths and common public
// metadata/static assets so browser side-requests don't trigger duplicate auth prompts.
// `/clubs/*` is included in the matcher so `handleClubRouting` can run; it
// bypasses admin auth internally.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|api/|proxy/|auth/|v1/|healthz|docs|openapi\\.json|favicon\\.ico|favicon\\.svg|robots\\.txt|sitemap\\.xml|site\\.webmanifest|manifest\\.webmanifest|apple-touch-icon\\.png).*)",
  ],
};
