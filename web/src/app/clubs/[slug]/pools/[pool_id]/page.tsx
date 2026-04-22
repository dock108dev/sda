import { notFound } from "next/navigation";
import Link from "next/link";
import { fetchPool, fetchPoolLeaderboard, fetchPoolField } from "@/lib/api/golfPools";
import { ClubNotFoundError, fetchClubBySlug } from "@/lib/api/clubs";
import type { GolfPoolLeaderboardEntry } from "@/lib/api/golfPoolTypes";
import EntryForm from "./EntryForm";

interface PageProps {
  params: Promise<{ slug: string; pool_id: string }>;
}

/** Pre-render known pool pages at build time; all others render on-demand. */
export async function generateStaticParams(): Promise<{ slug: string; pool_id: string }[]> {
  return [];
}

export default async function PoolPage({ params }: PageProps) {
  const { slug, pool_id } = await params;
  const poolId = Number(pool_id);

  if (isNaN(poolId)) {
    notFound();
  }

  // Verify the club exists and is active
  let club;
  try {
    club = await fetchClubBySlug(slug);
  } catch (err) {
    if (err instanceof ClubNotFoundError) {
      notFound();
    }
    throw err;
  }

  // Fetch pool details — 404 if pool doesn't exist
  let pool;
  try {
    pool = await fetchPool(poolId);
  } catch (err) {
    if (err instanceof Error && err.message.includes("(404)")) {
      notFound();
    }
    throw err;
  }

  // Fetch leaderboard (may be empty before scoring runs)
  let leaderboard: GolfPoolLeaderboardEntry[] = [];
  try {
    leaderboard = await fetchPoolLeaderboard(poolId);
  } catch {
    // Leaderboard not yet available — show empty state
  }

  // Fetch field for entry form (only needed when pool accepts entries)
  const acceptsEntries = pool.status === "open";

  let fieldData = null;
  if (acceptsEntries) {
    try {
      fieldData = await fetchPoolField(poolId);
    } catch {
      // Field data unavailable — entry form will be hidden
    }
  }

  const pickCount: number =
    typeof pool.rules?.pick_count === "number" ? pool.rules.pick_count : 6;

  return (
    <main style={{ maxWidth: "900px", margin: "0 auto", padding: "2rem" }}>
      {/* Breadcrumb */}
      <nav style={{ fontSize: "0.85rem", color: "#64748b", marginBottom: "1.5rem" }}>
        <Link href={`/clubs/${slug}`} style={{ color: "#1e40af" }}>
          {club.name}
        </Link>
        {" / "}
        {pool.name}
      </nav>

      <h1 style={{ fontSize: "1.75rem", fontWeight: 700, marginBottom: "0.25rem" }}>
        {pool.name}
      </h1>
      <div style={{ fontSize: "0.9rem", color: "#64748b", marginBottom: "2rem" }}>
        Status: <strong>{pool.status}</strong>
        {pool.entry_deadline && (
          <> &middot; Entries close {new Date(pool.entry_deadline).toLocaleDateString()}</>
        )}
      </div>

      {/* Leaderboard */}
      <section style={{ marginBottom: "2.5rem" }}>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem" }}>
          Leaderboard
        </h2>
        {leaderboard.length === 0 ? (
          <p style={{ color: "#64748b" }}>No scores yet — check back once the tournament begins.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #e2e8f0", textAlign: "left" }}>
                <th style={{ padding: "0.5rem" }}>Rank</th>
                <th style={{ padding: "0.5rem" }}>Entry</th>
                <th style={{ padding: "0.5rem", textAlign: "right" }}>Score</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((entry: GolfPoolLeaderboardEntry) => (
                <tr key={entry.entry_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "0.5rem" }}>
                    {entry.rank != null ? (entry.is_tied ? `T${entry.rank}` : entry.rank) : "—"}
                  </td>
                  <td style={{ padding: "0.5rem" }}>
                    {entry.entry_name ?? entry.email}
                  </td>
                  <td style={{ padding: "0.5rem", textAlign: "right", fontWeight: 600 }}>
                    {entry.aggregate_score != null
                      ? entry.aggregate_score > 0
                        ? `+${entry.aggregate_score}`
                        : String(entry.aggregate_score)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Entry form */}
      {acceptsEntries && (
        <section>
          <h2 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem" }}>
            Submit Your Entry
          </h2>
          {fieldData ? (
            <EntryForm poolId={poolId} pickCount={pickCount} field={fieldData} />
          ) : (
            <p style={{ color: "#64748b" }}>
              Player field not yet available. Check back soon.
            </p>
          )}
        </section>
      )}
    </main>
  );
}
