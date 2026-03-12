import type { RosterBatter } from "@/lib/api/analytics";

interface LineupSlot {
  external_ref: string;
  name: string;
}

export type { LineupSlot };

export function LineupEditor({
  lineup,
  batters,
  onChange,
}: {
  lineup: LineupSlot[];
  batters: RosterBatter[];
  onChange: (index: number, externalRef: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
      {Array.from({ length: 9 }, (_, i) => {
        const slot = lineup[i];
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ width: "24px", fontSize: "0.8rem", color: "var(--text-muted)", textAlign: "right" }}>
              {i + 1}.
            </span>
            <select
              value={slot?.external_ref || ""}
              onChange={(e) => onChange(i, e.target.value)}
              style={{ flex: 1, fontSize: "0.85rem" }}
            >
              <option value="">Select batter</option>
              {batters.map((b) => (
                <option key={b.external_ref} value={b.external_ref}>
                  {b.name} ({b.games_played}G)
                </option>
              ))}
            </select>
          </div>
        );
      })}
      {batters.length === 0 && (
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          No roster data available. Select a team first.
        </p>
      )}
    </div>
  );
}
