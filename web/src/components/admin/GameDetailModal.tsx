"use client";

import { type BatchSimGameResult, type ScoreEntry } from "@/lib/api/analyticsTypes";

interface GameDetailModalProps {
  game: BatchSimGameResult;
  sport: string;
  onClose: () => void;
  outcome?: {
    actual_home_score?: number;
    actual_away_score?: number;
    correct_winner?: boolean;
    brier_score?: number;
  };
}

export function GameDetailModal({ game, sport, onClose, outcome }: GameDetailModalProps) {
  const s = sport.toLowerCase();

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={modalStyle} onClick={(e) => e.stopPropagation()}>
        <div style={headerStyle}>
          <h3 style={{ margin: 0 }}>{game.away_team} @ {game.home_team}</h3>
          <button onClick={onClose} style={closeBtnStyle}>X</button>
        </div>

        {/* Projected Score */}
        <Section title="Projected Score">
          <div style={scoreRowStyle}>
            <ScoreBox
              label={game.home_team}
              score={game.average_home_score}
              std={game.score_std_home}
              wp={game.home_win_probability}
            />
            <span style={{ fontSize: "1.5rem", color: "#9ca3af", alignSelf: "center" }}>vs</span>
            <ScoreBox
              label={game.away_team}
              score={game.average_away_score}
              std={game.score_std_away}
              wp={game.away_win_probability}
            />
          </div>
          <div style={metaRowStyle}>
            <MetaItem label="Iterations" value={game.iterations?.toLocaleString() ?? "-"} />
            <MetaItem label="Source" value={game.probability_source ?? "-"} />
            <MetaItem
              label="WP Confidence"
              value={game.home_wp_std_dev != null ? `\u00B1${(game.home_wp_std_dev * 100).toFixed(1)}%` : "-"}
            />
            <MetaItem label="Profile Games" value={`${game.profile_games_home ?? "?"} / ${game.profile_games_away ?? "?"}`} />
          </div>
        </Section>

        {/* Most Common Scores */}
        {game.most_common_scores && game.most_common_scores.length > 0 && (
          <Section title="Most Likely Final Scores">
            <div style={scoresGridStyle}>
              {game.most_common_scores.slice(0, 8).map((s: ScoreEntry, i: number) => (
                <div key={i} style={scoreChipStyle}>
                  <span style={{ fontWeight: 600 }}>{s.score}</span>
                  <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>{(s.probability * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Sport-Specific Stats */}
        {game.event_summary && (
          <Section title="Projected Box Score">
            {s === "mlb" && <MLBStats summary={game.event_summary} />}
            {(s === "nba" || s === "ncaab") && <BasketballStats summary={game.event_summary} sport={s} />}
            {s === "nhl" && <NHLStats summary={game.event_summary} />}
            {s === "nfl" && <NFLStats summary={game.event_summary} />}
            {game.event_summary.game && <GameShape game={game.event_summary.game} sport={s} />}
          </Section>
        )}

        {/* Outcome (if game is final) */}
        {outcome && outcome.actual_home_score != null && (
          <Section title="Actual Result">
            <div style={metaRowStyle}>
              <MetaItem label="Final Score" value={`${outcome.actual_home_score} - ${outcome.actual_away_score}`} />
              <MetaItem
                label="Prediction"
                value={outcome.correct_winner ? "Correct" : "Wrong"}
              />
              {outcome.brier_score != null && (
                <MetaItem label="Brier Score" value={outcome.brier_score.toFixed(4)} />
              )}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}


// --- Sub-components ---

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "1rem" }}>
      <h4 style={{ margin: "0 0 0.5rem 0", fontSize: "0.9rem", color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>{title}</h4>
      {children}
    </div>
  );
}

function ScoreBox({ label, score, std, wp }: { label: string; score?: number; std?: number; wp?: number }) {
  return (
    <div style={{ textAlign: "center", flex: 1 }}>
      <div style={{ fontSize: "0.85rem", color: "#6b7280" }}>{label}</div>
      <div style={{ fontSize: "2rem", fontWeight: 700 }}>
        {score != null ? score.toFixed(1) : "-"}
      </div>
      {std != null && <div style={{ fontSize: "0.8rem", color: "#9ca3af" }}>{"\u00B1"} {std.toFixed(1)}</div>}
      {wp != null && <div style={{ fontSize: "0.85rem", color: wp > 0.5 ? "#22c55e" : "#ef4444" }}>{(wp * 100).toFixed(1)}%</div>}
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{label}</div>
      <div style={{ fontSize: "0.9rem", fontWeight: 500, color: "#111827" }}>{value}</div>
    </div>
  );
}

function RateRow({ label, value }: { label: string; value?: number }) {
  if (value == null) return null;
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "0.15rem 0" }}>
      <span style={{ color: "#6b7280", fontSize: "0.85rem" }}>{label}</span>
      <span style={{ fontWeight: 500, fontSize: "0.85rem", color: "#111827" }}>{(value * 100).toFixed(1)}%</span>
    </div>
  );
}

function TwoColumnRates({ homeLabel, awayLabel, homeRates, awayRates, rateLabels }: {
  homeLabel: string; awayLabel: string;
  homeRates: Record<string, number>; awayRates: Record<string, number>;
  rateLabels: [string, string][];
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: "0.5rem" }}>
      <div>
        <div style={{ fontSize: "0.8rem", color: "#6b7280", textAlign: "center", marginBottom: "0.25rem" }}>{homeLabel}</div>
        {rateLabels.map(([key, label]) => <RateRow key={key} label={label} value={homeRates[key]} />)}
      </div>
      <div style={{ borderLeft: "1px solid #e5e7eb", margin: "0 0.5rem" }} />
      <div>
        <div style={{ fontSize: "0.8rem", color: "#6b7280", textAlign: "center", marginBottom: "0.25rem" }}>{awayLabel}</div>
        {rateLabels.map(([key, label]) => <RateRow key={key} label={label} value={awayRates[key]} />)}
      </div>
    </div>
  );
}

// --- Sport-Specific Components ---

function MLBStats({ summary }: { summary: { home: any; away: any } }) {
  const labels: [string, string][] = [
    ["k_pct", "Strikeout"],
    ["bb_pct", "Walk/HBP"],
    ["single_pct", "Single"],
    ["double_pct", "Double"],
    ["triple_pct", "Triple"],
    ["hr_pct", "Home Run"],
    ["out_pct", "Ball in Play Out"],
  ];
  return (
    <>
      <div style={metaRowStyle}>
        <MetaItem label="Avg PA (H)" value={summary.home?.avg_pa?.toFixed(1) ?? "-"} />
        <MetaItem label="Avg Hits (H)" value={summary.home?.avg_hits?.toFixed(1) ?? "-"} />
        <MetaItem label="Avg PA (A)" value={summary.away?.avg_pa?.toFixed(1) ?? "-"} />
        <MetaItem label="Avg Hits (A)" value={summary.away?.avg_hits?.toFixed(1) ?? "-"} />
      </div>
      <TwoColumnRates
        homeLabel="Home PA Mix" awayLabel="Away PA Mix"
        homeRates={summary.home?.rates || summary.home?.pa_rates || {}}
        awayRates={summary.away?.rates || summary.away?.pa_rates || {}}
        rateLabels={labels}
      />
    </>
  );
}

function BasketballStats({ summary, sport }: { summary: { home: any; away: any }; sport: string }) {
  const labels: [string, string][] = [
    ["two_pt_make_pct", "2PT Make"],
    ["two_pt_miss_pct", "2PT Miss"],
    ["three_pt_make_pct", "3PT Make"],
    ["three_pt_miss_pct", "3PT Miss"],
    ["ft_trip_pct", "FT Trip"],
    ["turnover_pct", "Turnover"],
  ];
  if (sport === "ncaab") labels.push(["orb_pct", "Off. Rebound"]);

  return (
    <>
      <div style={metaRowStyle}>
        <MetaItem label="FG%" value={summary.home?.fg_pct != null ? (summary.home.fg_pct * 100).toFixed(1) + "%" : "-"} />
        <MetaItem label="3PT%" value={summary.home?.fg3_pct != null ? (summary.home.fg3_pct * 100).toFixed(1) + "%" : "-"} />
        <MetaItem label="eFG%" value={summary.home?.efg_pct != null ? (summary.home.efg_pct * 100).toFixed(1) + "%" : "-"} />
        <MetaItem label="Poss" value={summary.home?.avg_possessions?.toFixed(0) ?? "-"} />
      </div>
      <TwoColumnRates
        homeLabel="Home Rates" awayLabel="Away Rates"
        homeRates={summary.home?.rates || {}}
        awayRates={summary.away?.rates || {}}
        rateLabels={labels}
      />
    </>
  );
}

function NHLStats({ summary }: { summary: { home: any; away: any } }) {
  const labels: [string, string][] = [
    ["goal_pct", "Goal"],
    ["save_pct", "Save"],
    ["blocked_pct", "Blocked"],
    ["missed_pct", "Missed"],
  ];
  return (
    <>
      <div style={metaRowStyle}>
        <MetaItem label="Avg Shots (H)" value={summary.home?.avg_shots?.toFixed(1) ?? "-"} />
        <MetaItem label="Shooting% (H)" value={summary.home?.shooting_pct != null ? (summary.home.shooting_pct * 100).toFixed(1) + "%" : "-"} />
        <MetaItem label="Avg Shots (A)" value={summary.away?.avg_shots?.toFixed(1) ?? "-"} />
        <MetaItem label="Shooting% (A)" value={summary.away?.shooting_pct != null ? (summary.away.shooting_pct * 100).toFixed(1) + "%" : "-"} />
      </div>
      <TwoColumnRates
        homeLabel="Home Shot Outcomes" awayLabel="Away Shot Outcomes"
        homeRates={summary.home?.rates || {}}
        awayRates={summary.away?.rates || {}}
        rateLabels={labels}
      />
    </>
  );
}

function NFLStats({ summary }: { summary: { home: any; away: any } }) {
  const labels: [string, string][] = [
    ["td_pct", "Touchdown"],
    ["fg_pct", "Field Goal"],
    ["punt_pct", "Punt"],
    ["turnover_pct", "Turnover"],
    ["downs_pct", "Turnover on Downs"],
  ];
  return (
    <>
      <div style={metaRowStyle}>
        <MetaItem label="Avg Drives (H)" value={summary.home?.avg_drives?.toFixed(1) ?? "-"} />
        <MetaItem label="Scoring% (H)" value={summary.home?.scoring_drive_pct != null ? (summary.home.scoring_drive_pct * 100).toFixed(1) + "%" : "-"} />
        <MetaItem label="Avg Drives (A)" value={summary.away?.avg_drives?.toFixed(1) ?? "-"} />
        <MetaItem label="Scoring% (A)" value={summary.away?.scoring_drive_pct != null ? (summary.away.scoring_drive_pct * 100).toFixed(1) + "%" : "-"} />
      </div>
      <TwoColumnRates
        homeLabel="Home Drive Outcomes" awayLabel="Away Drive Outcomes"
        homeRates={summary.home?.rates || {}}
        awayRates={summary.away?.rates || {}}
        rateLabels={labels}
      />
    </>
  );
}

function GameShape({ game, sport }: { game: any; sport: string }) {
  return (
    <div style={{ ...metaRowStyle, marginTop: "0.75rem", borderTop: "1px solid #e5e7eb", paddingTop: "0.75rem" }}>
      <MetaItem label="Avg Total" value={game.avg_total?.toFixed(1) ?? game.avg_total_runs?.toFixed(1) ?? "-"} />
      {game.extra_innings_pct != null && <MetaItem label="Extra Inn." value={(game.extra_innings_pct * 100).toFixed(1) + "%"} />}
      {game.shutout_pct != null && <MetaItem label="Shutout" value={(game.shutout_pct * 100).toFixed(1) + "%"} />}
      {game.overtime_pct != null && <MetaItem label="Overtime" value={(game.overtime_pct * 100).toFixed(1) + "%"} />}
      {game.shootout_pct != null && <MetaItem label="Shootout" value={(game.shootout_pct * 100).toFixed(1) + "%"} />}
      <MetaItem label="1-Score Game" value={(game.one_score_game_pct ?? game.one_run_game_pct ?? 0) * 100 > 0 ? ((game.one_score_game_pct ?? game.one_run_game_pct) * 100).toFixed(1) + "%" : "-"} />
    </div>
  );
}


// --- Styles ---

const overlayStyle: React.CSSProperties = {
  position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
  background: "rgba(0,0,0,0.3)", zIndex: 1000,
  display: "flex", alignItems: "center", justifyContent: "center",
  padding: "1rem",
};

const modalStyle: React.CSSProperties = {
  background: "#ffffff", borderRadius: "0.75rem", padding: "1.5rem",
  maxWidth: "700px", width: "100%", maxHeight: "85vh", overflowY: "auto",
  color: "#111827", boxShadow: "0 25px 50px rgba(0,0,0,0.15)",
};

const headerStyle: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  marginBottom: "1.25rem", borderBottom: "1px solid #e5e7eb", paddingBottom: "0.75rem",
};

const closeBtnStyle: React.CSSProperties = {
  background: "none", border: "none", color: "#6b7280", fontSize: "1.1rem",
  cursor: "pointer", padding: "0.25rem 0.5rem",
};

const scoreRowStyle: React.CSSProperties = {
  display: "flex", justifyContent: "space-around", alignItems: "center",
  marginBottom: "0.75rem",
};

const metaRowStyle: React.CSSProperties = {
  display: "flex", justifyContent: "space-around", gap: "1rem",
  flexWrap: "wrap", marginBottom: "0.5rem",
};

const scoresGridStyle: React.CSSProperties = {
  display: "flex", flexWrap: "wrap", gap: "0.5rem",
};

const scoreChipStyle: React.CSSProperties = {
  background: "#f9fafb", padding: "0.35rem 0.75rem", borderRadius: "0.5rem",
  display: "flex", gap: "0.5rem", alignItems: "center",
  border: "1px solid #e5e7eb", fontSize: "0.85rem",
};
