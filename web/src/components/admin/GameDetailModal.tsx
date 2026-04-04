"use client";

import { type BatchSimGameResult, type ScoreEntry, type BatterLine, type LineAnalysis } from "@/lib/api/analyticsTypes";

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

        {/* Line Analysis */}
        {game.line_analysis && (
          <Section title="Line Analysis">
            <LineAnalysisDisplay la={game.line_analysis} home={game.home_team} away={game.away_team} />
          </Section>
        )}

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

        {/* Projected Lineup & Pitching (MLB with lineup_info) */}
        {s === "mlb" && game.lineup_info && (
          <>
            <Section title="Projected Pitching Matchup">
              <div style={pitcherMatchupStyle}>
                <div style={{ textAlign: "center", flex: 1 }}>
                  <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{game.home_team} SP</div>
                  <div style={{ fontSize: "1rem", fontWeight: 600, color: "#111827" }}>
                    {game.lineup_info.home_starter?.name ?? "Unknown"}
                  </div>
                </div>
                <span style={{ color: "#9ca3af", fontSize: "0.85rem" }}>vs</span>
                <div style={{ textAlign: "center", flex: 1 }}>
                  <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{game.away_team} SP</div>
                  <div style={{ fontSize: "1rem", fontWeight: 600, color: "#111827" }}>
                    {game.lineup_info.away_starter?.name ?? "Unknown"}
                  </div>
                </div>
              </div>
            </Section>
            <Section title={`${game.home_team} Projected Batting`}>
              <BattingTable batters={game.lineup_info.home_batting} />
            </Section>
            <Section title={`${game.away_team} Projected Batting`}>
              <BattingTable batters={game.lineup_info.away_batting} />
            </Section>
          </>
        )}

        {/* Fallback: Sport-Specific aggregate stats (non-lineup or non-MLB) */}
        {game.event_summary && !(s === "mlb" && game.lineup_info) && (
          <Section title="Projected Box Score">
            {s === "mlb" && <MLBStats summary={game.event_summary} />}
            {(s === "nba" || s === "ncaab") && <BasketballStats summary={game.event_summary} sport={s} />}
            {s === "nhl" && <NHLStats summary={game.event_summary} />}
            {s === "nfl" && <NFLStats summary={game.event_summary} />}
            {game.event_summary.game && <GameShape game={game.event_summary.game} sport={s} />}
          </Section>
        )}

        {/* Game shape for MLB lineup mode */}
        {s === "mlb" && game.lineup_info && game.event_summary?.game && (
          <Section title="Game Shape">
            <GameShape game={game.event_summary.game} sport={s} />
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

function fmtML(ml: number): string {
  return ml >= 0 ? `+${ml}` : `${ml}`;
}

function fmtEdge(edge: number): string {
  const pct = (edge * 100).toFixed(1);
  return edge >= 0 ? `+${pct}%` : `${pct}%`;
}

function edgeColor(edge: number): string {
  if (edge >= 0.03) return "#16a34a";
  if (edge >= 0.01) return "#65a30d";
  if (edge > -0.01) return "#6b7280";
  return "#dc2626";
}

function LineAnalysisDisplay({ la, home, away }: { la: LineAnalysis; home: string; away: string }) {
  const isClosing = la.line_type === "closing";
  const mlLabel = isClosing ? "Close ML" : "Current ML";
  return (
    <div>
      <table style={{ ...battingTableStyle, marginBottom: "0.5rem" }}>
        <thead>
          <tr>
            <th style={{ ...thStyle, textAlign: "left", minWidth: "80px" }}>Side</th>
            <th style={thStyle}>{mlLabel}</th>
            <th style={thStyle}>Mkt Prob</th>
            <th style={thStyle}>Model Prob</th>
            <th style={thStyle}>Model Line</th>
            <th style={thStyle}>Edge</th>
            <th style={thStyle}>EV%</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={{ ...tdStyle, textAlign: "left", fontWeight: 500 }}>{home}</td>
            <td style={tdStyle}>{fmtML(la.market_home_ml)}</td>
            <td style={tdStyle}>{(la.market_home_wp * 100).toFixed(1)}%</td>
            <td style={{ ...tdStyle, fontWeight: 600 }}>{(la.model_home_wp * 100).toFixed(1)}%</td>
            <td style={{ ...tdStyle, fontWeight: 500 }}>{fmtML(la.model_home_line)}</td>
            <td style={{ ...tdStyle, fontWeight: 600, color: edgeColor(la.home_edge) }}>{fmtEdge(la.home_edge)}</td>
            <td style={{ ...tdStyle, color: la.home_ev_pct >= 0 ? "#16a34a" : "#dc2626" }}>{la.home_ev_pct >= 0 ? "+" : ""}{la.home_ev_pct.toFixed(1)}%</td>
          </tr>
          <tr style={{ background: "#f9fafb" }}>
            <td style={{ ...tdStyle, textAlign: "left", fontWeight: 500 }}>{away}</td>
            <td style={tdStyle}>{fmtML(la.market_away_ml)}</td>
            <td style={tdStyle}>{(la.market_away_wp * 100).toFixed(1)}%</td>
            <td style={{ ...tdStyle, fontWeight: 600 }}>{(la.model_away_wp * 100).toFixed(1)}%</td>
            <td style={{ ...tdStyle, fontWeight: 500 }}>{fmtML(la.model_away_line)}</td>
            <td style={{ ...tdStyle, fontWeight: 600, color: edgeColor(la.away_edge) }}>{fmtEdge(la.away_edge)}</td>
            <td style={{ ...tdStyle, color: la.away_ev_pct >= 0 ? "#16a34a" : "#dc2626" }}>{la.away_ev_pct >= 0 ? "+" : ""}{la.away_ev_pct.toFixed(1)}%</td>
          </tr>
        </tbody>
      </table>
      <div style={{ fontSize: "0.7rem", color: "#9ca3af", textAlign: "right" }}>
        {isClosing ? "Closing" : "Current"} line via {la.provider} (devigged via Shin)
      </div>
    </div>
  );
}

function BattingTable({ batters }: { batters: BatterLine[] }) {
  if (!batters || batters.length === 0) {
    return <div style={{ fontSize: "0.8rem", color: "#9ca3af" }}>No lineup data</div>;
  }
  const cols: { key: keyof BatterLine; label: string }[] = [
    { key: "K", label: "K%" },
    { key: "BB", label: "BB%" },
    { key: "1B", label: "1B%" },
    { key: "2B", label: "2B%" },
    { key: "3B", label: "3B%" },
    { key: "HR", label: "HR%" },
    { key: "BIP", label: "BIP%" },
  ];
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={battingTableStyle}>
        <thead>
          <tr>
            <th style={{ ...thStyle, textAlign: "left", minWidth: "110px" }}>#</th>
            {cols.map((c) => (
              <th key={c.key} style={thStyle}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {batters.map((b, i) => (
            <tr key={i} style={i % 2 === 0 ? {} : { background: "#f9fafb" }}>
              <td style={{ ...tdStyle, textAlign: "left", fontWeight: 500 }}>
                <span style={{ color: "#9ca3af", marginRight: "0.4rem" }}>{i + 1}.</span>
                {b.name}
              </td>
              {cols.map((c) => (
                <td key={c.key} style={{
                  ...tdStyle,
                  color: c.key === "HR" && (b[c.key] as number) >= 4 ? "#dc2626" :
                         c.key === "K" && (b[c.key] as number) >= 25 ? "#9ca3af" : "#111827",
                  fontWeight: c.key === "HR" && (b[c.key] as number) >= 4 ? 600 : 400,
                }}>
                  {(b[c.key] as number).toFixed(1)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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

const pitcherMatchupStyle: React.CSSProperties = {
  display: "flex", justifyContent: "space-around", alignItems: "center",
  padding: "0.5rem 0",
};

const battingTableStyle: React.CSSProperties = {
  width: "100%", borderCollapse: "collapse", fontSize: "0.8rem",
};

const thStyle: React.CSSProperties = {
  textAlign: "center", padding: "0.3rem 0.4rem", fontSize: "0.7rem",
  color: "#6b7280", fontWeight: 600, textTransform: "uppercase",
  borderBottom: "1px solid #e5e7eb", letterSpacing: "0.03em",
};

const tdStyle: React.CSSProperties = {
  textAlign: "center", padding: "0.25rem 0.4rem", fontSize: "0.8rem",
  borderBottom: "1px solid #f3f4f6",
};
