import React from "react";
import { notFound } from "next/navigation";
import Link from "next/link";
import { fetchClubBySlug, ClubNotFoundError } from "@/lib/api/clubs";
import type { ActivePool } from "@/lib/api/clubs";

interface PageProps {
  params: Promise<{ slug: string }>;
}

/** Pre-render known slugs at build time; all others render on-demand. */
export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return [];
}

export default async function ClubPage({ params }: PageProps) {
  const { slug } = await params;

  let club;
  try {
    club = await fetchClubBySlug(slug);
  } catch (err) {
    if (err instanceof ClubNotFoundError) {
      notFound();
    }
    throw err;
  }

  const primaryColor = club.branding?.primary_color;

  return (
    <main
      style={{
        maxWidth: "800px",
        margin: "0 auto",
        padding: "2rem",
        ...(primaryColor ? { "--club-primary": primaryColor } as React.CSSProperties : {}),
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "0.5rem" }}>
        {club.branding?.logo_url && (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element -- operator HTTPS logos; origins not fixed */}
            <img
              src={club.branding.logo_url}
              alt={`${club.name} logo`}
              style={{ height: "48px", width: "auto", objectFit: "contain" }}
            />
          </>
        )}
        <h1
          style={{
            fontSize: "2rem",
            fontWeight: 700,
            color: primaryColor ?? undefined,
          }}
        >
          {club.name}
        </h1>
      </div>
      <p style={{ color: "#64748b", marginBottom: "2rem" }}>
        Golf pool leaderboards and entry
      </p>

      <h2 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem" }}>
        Active Pools
      </h2>

      {club.active_pools.length === 0 ? (
        <p style={{ color: "#64748b" }}>No active pools at this time.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {club.active_pools.map((pool: ActivePool) => (
            <li
              key={pool.pool_id}
              style={{
                border: "1px solid #e2e8f0",
                borderRadius: "8px",
                padding: "1rem 1.25rem",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <Link
                  href={`/clubs/${slug}/pools/${pool.pool_id}`}
                  style={{ fontWeight: 600, color: "#1e40af", textDecoration: "none" }}
                >
                  {pool.name}
                </Link>
                <div style={{ fontSize: "0.85rem", color: "#64748b", marginTop: "0.25rem" }}>
                  Status: <strong>{pool.status}</strong>
                  {pool.entry_deadline && (
                    <> &middot; Entries close {new Date(pool.entry_deadline).toLocaleDateString()}</>
                  )}
                </div>
              </div>
              <Link
                href={`/clubs/${slug}/pools/${pool.pool_id}`}
                style={{
                  padding: "0.4rem 0.9rem",
                  background: "#1e40af",
                  color: "#fff",
                  borderRadius: "6px",
                  textDecoration: "none",
                  fontSize: "0.85rem",
                }}
              >
                View &rarr;
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
