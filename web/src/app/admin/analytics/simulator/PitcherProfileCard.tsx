import type { PitcherAnalytics } from "@/lib/api/analytics";

const METRIC_LABELS: Record<string, string> = {
  strikeout_rate: "K Rate",
  walk_rate: "BB Rate",
  contact_suppression: "Contact Supp.",
  power_suppression: "Power Supp.",
};

export function formatPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

export function PitcherProfileCard({ label, pitcher }: { label: string; pitcher: PitcherAnalytics }) {
  const profile = pitcher.adjusted_profile;
  const raw = pitcher.raw_profile;
  const isRegressed = pitcher.avg_ip != null && pitcher.avg_ip < 5.0 && raw != null;

  return (
    <div>
      <div style={{ fontWeight: 600, fontSize: "0.9rem", marginBottom: "0.25rem" }}>
        {pitcher.name || label}
      </div>
      {pitcher.avg_ip != null && (
        <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
          {pitcher.avg_ip.toFixed(1)} avg IP/game
          {isRegressed && (
            <span style={{ color: "#f59e0b", marginLeft: "0.5rem" }}>
              (regressed toward league avg)
            </span>
          )}
        </div>
      )}
      {profile ? (
        <table style={{ width: "100%", fontSize: "0.8rem", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <th style={{ textAlign: "left", padding: "0.25rem 0" }}>Metric</th>
              {isRegressed && raw && <th style={{ textAlign: "right", padding: "0.25rem 0" }}>Raw</th>}
              <th style={{ textAlign: "right", padding: "0.25rem 0" }}>{isRegressed ? "Adjusted" : "Value"}</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(profile).map(([key, val]) => (
              <tr key={key} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "0.25rem 0" }}>{METRIC_LABELS[key] || key}</td>
                {isRegressed && raw && (
                  <td style={{ textAlign: "right", padding: "0.25rem 0", color: "var(--text-muted)" }}>
                    {formatPct(raw[key] ?? 0)}
                  </td>
                )}
                <td style={{ textAlign: "right", padding: "0.25rem 0", fontWeight: 500 }}>
                  {formatPct(val)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Using league-average defaults</p>
      )}
    </div>
  );
}

export function MetricsTable({ metrics, label }: { metrics: Record<string, number>; label: string }) {
  return (
    <div>
      <div style={{ fontWeight: 500, fontSize: "0.85rem", marginBottom: "0.25rem" }}>{label}</div>
      <table style={{ width: "100%", fontSize: "0.8rem", borderCollapse: "collapse" }}>
        <tbody>
          {Object.entries(metrics).map(([key, val]) => (
            <tr key={key} style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "0.25rem 0" }}>{METRIC_LABELS[key] || key}</td>
              <td style={{ textAlign: "right", padding: "0.25rem 0" }}>{formatPct(val)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
