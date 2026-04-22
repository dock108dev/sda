"use client";

import { useState } from "react";
import { submitPoolEntry } from "@/lib/api/golfPools";
import type { PoolFieldResponse } from "@/lib/api/golfPools";

interface PickSlot {
  dg_id: number;
  pick_slot: number;
  bucket_number?: number;
}

interface Props {
  poolId: number;
  pickCount: number;
  field: PoolFieldResponse;
}

export default function EntryForm({ poolId, pickCount, field }: Props) {
  const [email, setEmail] = useState("");
  const [entryName, setEntryName] = useState("");
  const [picks, setPicks] = useState<Record<number, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const players =
    field.format === "flat" && field.field
      ? field.field.filter((p) => p.status !== "wd")
      : [];

  const handlePickChange = (slot: number, dgId: number) => {
    setPicks((prev) => ({ ...prev, [slot]: dgId }));
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError("Email is required.");
      return;
    }

    const slotNumbers = Array.from({ length: pickCount }, (_, i) => i + 1);
    const filledPicks = slotNumbers.every((slot) => picks[slot] != null && picks[slot] !== 0);
    if (!filledPicks) {
      setError(`Please select all ${pickCount} picks.`);
      return;
    }

    const pickPayload: PickSlot[] = slotNumbers.map((slot) => ({
      dg_id: picks[slot],
      pick_slot: slot,
    }));

    setSubmitting(true);
    try {
      await submitPoolEntry(poolId, {
        email: email.trim(),
        entry_name: entryName.trim() || undefined,
        picks: pickPayload,
      });
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed.");
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div style={{ padding: "1.5rem", background: "#f0fdf4", borderRadius: "8px", color: "#166534" }}>
        <strong>Entry submitted!</strong> Check your email for confirmation.
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {error && (
        <div style={{ padding: "0.75rem", background: "#fef2f2", borderRadius: "6px", color: "#991b1b" }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <label htmlFor="email" style={{ fontWeight: 600, fontSize: "0.9rem" }}>
          Email *
        </label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          style={{ padding: "0.5rem", border: "1px solid #cbd5e1", borderRadius: "6px" }}
        />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <label htmlFor="entry-name" style={{ fontWeight: 600, fontSize: "0.9rem" }}>
          Entry Name
        </label>
        <input
          id="entry-name"
          type="text"
          value={entryName}
          onChange={(e) => setEntryName(e.target.value)}
          placeholder="Optional display name"
          style={{ padding: "0.5rem", border: "1px solid #cbd5e1", borderRadius: "6px" }}
        />
      </div>

      {Array.from({ length: pickCount }, (_, i) => i + 1).map((slot) => (
        <div key={slot} style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          <label htmlFor={`pick-${slot}`} style={{ fontWeight: 600, fontSize: "0.9rem" }}>
            Pick {slot} *
          </label>
          <select
            id={`pick-${slot}`}
            value={picks[slot] ?? 0}
            onChange={(e) => handlePickChange(slot, Number(e.target.value))}
            required
            style={{ padding: "0.5rem", border: "1px solid #cbd5e1", borderRadius: "6px" }}
          >
            <option value={0}>Select a player...</option>
            {players.map((p) => (
              <option
                key={p.dg_id}
                value={p.dg_id}
                disabled={Object.values(picks).includes(p.dg_id) && picks[slot] !== p.dg_id}
              >
                {p.player_name ?? `Player #${p.dg_id}`}
              </option>
            ))}
          </select>
        </div>
      ))}

      <button
        type="submit"
        disabled={submitting}
        style={{
          padding: "0.75rem",
          background: "#1e40af",
          color: "#fff",
          border: "none",
          borderRadius: "6px",
          fontWeight: 600,
          cursor: submitting ? "not-allowed" : "pointer",
          opacity: submitting ? 0.7 : 1,
        }}
      >
        {submitting ? "Submitting..." : "Submit Entry"}
      </button>
    </form>
  );
}
