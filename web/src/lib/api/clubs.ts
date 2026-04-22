/** API client functions for public club endpoints. */

import { request } from "./sportsAdmin/client";

export interface ActivePool {
  pool_id: number;
  name: string;
  status: string;
  tournament_id: number | null;
  entry_deadline: string | null;
  allow_self_service_entry: boolean;
}

export interface ClubBranding {
  logo_url?: string;
  primary_color?: string;
  accent_color?: string;
}

export interface ClubPublic {
  club_id: string;
  name: string;
  slug: string;
  active_pools: ActivePool[];
  branding?: ClubBranding;
}

export class ClubNotFoundError extends Error {
  constructor(slug: string) {
    super(`Club not found: ${slug}`);
    this.name = "ClubNotFoundError";
  }
}

export async function fetchClubBySlug(slug: string): Promise<ClubPublic> {
  try {
    return await request<ClubPublic>(`/api/v1/clubs/${encodeURIComponent(slug)}`);
  } catch (err) {
    if (err instanceof Error && err.message.includes("(404)")) {
      throw new ClubNotFoundError(slug);
    }
    throw err;
  }
}

export async function updateClubBranding(
  clubId: string,
  branding: ClubBranding,
): Promise<{ club_id: string; branding: ClubBranding }> {
  return request(`/api/v1/clubs/${encodeURIComponent(clubId)}/branding`, {
    method: "PUT",
    body: JSON.stringify(branding),
  });
}
