"use client";

import { ANALYTICS_SPORTS, type AnalyticsSport } from "@/lib/constants/analytics";

interface SportSelectorProps {
  value: AnalyticsSport;
  onChange: (sport: AnalyticsSport) => void;
  sports?: readonly AnalyticsSport[];
}

export function SportSelector({ value, onChange, sports = ANALYTICS_SPORTS }: SportSelectorProps) {
  return (
    <div style={{ display: "flex", gap: "0.25rem", marginBottom: "1rem" }}>
      {sports.map((s) => (
        <button
          key={s}
          onClick={() => onChange(s)}
          style={{
            padding: "0.4rem 0.9rem",
            borderRadius: "0.375rem",
            border: "1px solid var(--border-color, #d1d5db)",
            background: value === s ? "var(--accent-color, #2563eb)" : "transparent",
            color: value === s ? "#fff" : "var(--text-primary, #374151)",
            fontWeight: value === s ? 600 : 400,
            fontSize: "0.85rem",
            cursor: "pointer",
            transition: "all 0.15s",
          }}
        >
          {s}
        </button>
      ))}
    </div>
  );
}
