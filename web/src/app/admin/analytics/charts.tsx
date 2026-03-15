"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";

/* ------------------------------------------------------------------ */
/* Score distribution bar chart (pregame simulator)                     */
/* ------------------------------------------------------------------ */

interface ScoreEntry {
  score: string;
  probability: number;
}

export function ScoreDistributionChart({ data }: { data: ScoreEntry[] }) {
  const chartData = data.map((d) => ({
    score: d.score,
    pct: +(d.probability * 100).toFixed(1),
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="score" tick={{ fontSize: 12 }} />
        <YAxis tick={{ fontSize: 12 }} unit="%" />
        <Tooltip formatter={(v) => `${v}%`} />
        <Bar dataKey="pct" name="Probability" radius={[4, 4, 0, 0]}>
          {chartData.map((_, i) => (
            <Cell key={i} fill={i === 0 ? "#3b82f6" : "#93c5fd"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------------------ */
/* Pitch-level probabilities grouped bar chart                         */
/* ------------------------------------------------------------------ */

/** League-average pitch-level outcome probabilities (2024 MLB season). */
const LEAGUE_AVG_PA: Record<string, number> = {
  strikeout: 0.22,
  walk: 0.08,
  single: 0.15,
  double: 0.05,
  triple: 0.01,
  home_run: 0.03,
};

export function PAProbabilitiesChart({
  homeProbs,
  awayProbs,
  homeLabel,
  awayLabel,
}: {
  homeProbs: Record<string, number>;
  awayProbs: Record<string, number>;
  homeLabel: string;
  awayLabel: string;
}) {
  const events = Object.keys(homeProbs);
  const chartData = events.map((key) => {
    const event = key.replace("_probability", "");
    return {
      event,
      [homeLabel]: +((homeProbs[key] ?? 0) * 100).toFixed(1),
      [awayLabel]: +((awayProbs[key] ?? 0) * 100).toFixed(1),
      "League Avg": +((LEAGUE_AVG_PA[event] ?? 0) * 100).toFixed(1),
    };
  });

  return (
    <>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="event" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 12 }} unit="%" />
          <Tooltip formatter={(v) => `${v}%`} />
          <Legend />
          <Bar dataKey={homeLabel} fill="#3b82f6" radius={[3, 3, 0, 0]} />
          <Bar dataKey={awayLabel} fill="#f97316" radius={[3, 3, 0, 0]} />
          <Bar dataKey="League Avg" fill="#9ca3af" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>
        League averages: 2024 MLB season
      </p>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Calibration accuracy chart (model performance)                      */
/* ------------------------------------------------------------------ */

interface CalibrationEntry {
  label: string;
  predicted: number;
  actual: number;
}

export function CalibrationChart({ data }: { data: CalibrationEntry[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 12 }} unit="%" domain={[0, 100]} />
        <Tooltip formatter={(v) => `${Number(v).toFixed(1)}%`} />
        <Legend />
        <Bar dataKey="predicted" name="Predicted WP" fill="#3b82f6" radius={[3, 3, 0, 0]} />
        <Bar dataKey="actual" name="Actual Win %" fill="#22c55e" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
