import type { DataFreshness } from "@/lib/api/analytics";

export function DataFreshnessDisplay({
  freshness,
  homeLabel,
  awayLabel,
}: {
  freshness: { home: DataFreshness; away: DataFreshness };
  homeLabel: string;
  awayLabel: string;
}) {
  const isStale = (newest: string) => {
    const d = new Date(newest);
    const now = new Date();
    const diffDays = (now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24);
    return diffDays > 3;
  };

  const renderSide = (label: string, data: DataFreshness) => (
    <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
      <strong>{label}:</strong> {data.games_used} games ({data.oldest_game} to {data.newest_game})
      {isStale(data.newest_game) && (
        <span style={{ color: "#f59e0b", marginLeft: "0.5rem" }}>
          Data may be stale
        </span>
      )}
    </div>
  );

  return (
    <div style={{ marginTop: "0.75rem", paddingTop: "0.5rem", borderTop: "1px solid var(--border)" }}>
      {renderSide(homeLabel, freshness.home)}
      {renderSide(awayLabel, freshness.away)}
    </div>
  );
}
