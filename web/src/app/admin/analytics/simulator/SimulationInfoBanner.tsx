import type { SimulationInfo } from "@/lib/api/analytics";

const MODE_LABELS: Record<string, string> = {
  ml: "ML Model",
  ensemble: "Ensemble",
  rule_based: "Rule-Based",
  default: "Default",
};

export function SimulationInfoBanner({ info }: { info: SimulationInfo }) {
  const isFallback = info.fallback_used;
  const bannerStyle: React.CSSProperties = {
    padding: "0.75rem 1rem",
    borderRadius: "0.5rem",
    fontSize: "0.85rem",
    lineHeight: 1.5,
    border: "1px solid",
    borderColor: isFallback ? "#f59e0b" : "var(--border)",
    backgroundColor: isFallback ? "rgba(245, 158, 11, 0.08)" : "rgba(59, 130, 246, 0.05)",
  };

  return (
    <div style={bannerStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
        <span style={{
          display: "inline-block",
          padding: "0.15rem 0.5rem",
          borderRadius: "0.25rem",
          fontSize: "0.75rem",
          fontWeight: 600,
          backgroundColor: isFallback ? "#f59e0b" : "#3b82f6",
          color: "#fff",
        }}>
          {MODE_LABELS[info.executed_mode] || info.executed_mode}
        </span>
        {isFallback && (
          <span style={{ color: "#b45309" }}>
            Requested {MODE_LABELS[info.requested_mode] || info.requested_mode} but fell back: {info.fallback_reason}
          </span>
        )}
        {!isFallback && (
          <span style={{ color: "var(--text-muted)" }}>
            Probability source: {MODE_LABELS[info.executed_mode] || info.executed_mode}
          </span>
        )}
      </div>
      {info.model_info && (
        <div style={{ marginTop: "0.35rem", fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Model v{info.model_info.version}
          {info.model_info.trained_at && `, trained ${info.model_info.trained_at}`}
          {info.model_info.metrics?.accuracy != null && `, accuracy: ${(info.model_info.metrics.accuracy * 100).toFixed(1)}%`}
        </div>
      )}
      {info.warnings.length > 0 && (
        <div style={{ marginTop: "0.35rem", fontSize: "0.8rem", color: "#ef4444" }}>
          Warnings: {info.warnings.join(", ")}
        </div>
      )}
    </div>
  );
}
