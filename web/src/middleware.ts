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
 * Resolves club context from the incoming request.
 *
 * Path-based mode (SUBDOMAIN_ROUTING=false, default):
 *   /clubs/<slug>/** → sets X-Club-Slug header and continues
 *
 * Subdomain mode (SUBDOMAIN_ROUTING=true):
 *   /clubs/<slug>/** → 301 redirect to https://<slug>.<BASE_DOMAIN>/<rest>
 *   <slug>.<BASE_DOMAIN>/** → sets X-Club-Slug header and continues
 */
export function middleware(request: NextRequest): NextResponse {
  const subdomainRouting = process.env.SUBDOMAIN_ROUTING === "true";
  const baseDomain = process.env.BASE_DOMAIN ?? "localhost";
  const pathname = request.nextUrl.pathname;

  if (subdomainRouting) {
    // Legacy path-based club URL → 301 to subdomain
    const pathMatch = CLUB_PATH_RE.exec(pathname);
    if (pathMatch) {
      const slug = pathMatch[1];
      const rest = pathMatch[2] ?? "";
      return NextResponse.redirect(
        `https://${slug}.${baseDomain}${rest}`,
        301,
      );
    }

    // Subdomain request → extract slug from Host header
    const host = (request.headers.get("host") ?? "").split(":")[0];
    const slug = extractSubdomainSlug(host, baseDomain);
    if (slug) {
      const requestHeaders = new Headers(request.headers);
      requestHeaders.set("x-club-slug", slug);
      return NextResponse.next({ request: { headers: requestHeaders } });
    }

    return NextResponse.next();
  }

  // Default path-based mode
  const pathMatch = CLUB_PATH_RE.exec(pathname);
  if (pathMatch) {
    const requestHeaders = new Headers(request.headers);
    requestHeaders.set("x-club-slug", pathMatch[1]);
    return NextResponse.next({ request: { headers: requestHeaders } });
  }

  return NextResponse.next();
}

export const config = {
  // Run on all paths so subdomain mode can intercept arbitrary routes.
  // Excludes Next.js internals and static assets.
  matcher: "/((?!_next/static|_next/image|favicon.ico).*)",
};
