/**
 * Type definitions for the /api/v1/clubs/, /api/v1/billing/, and
 * /api/v1/commerce/ consumer endpoints. Mirrors the camelCase response
 * shapes emitted by the FastAPI routers under those prefixes.
 */

export interface ActivePool {
  poolId: number;
  name: string;
  status: string;
  tournamentId: number | null;
  entryDeadline: string | null;
  allowSelfServiceEntry: boolean;
}

export interface ClubBranding {
  logoUrl?: string;
  primaryColor?: string;
  accentColor?: string;
}

export interface ClubPublic {
  clubId: string;
  name: string;
  slug: string;
  activePools: ActivePool[];
  branding?: ClubBranding;
}

export interface ClubSummary {
  clubId: string;
  name: string;
  slug: string;
}

export interface BrandingResponse {
  clubId: string;
  branding: Record<string, string>;
}

export interface MemberResponse {
  userId: number;
  email: string;
  role: string;
  acceptedAt: string | null;
}

export interface CheckoutResponse {
  checkoutUrl: string;
  sessionToken: string;
}

export interface PortalResponse {
  url: string;
}
