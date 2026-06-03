"use client";

import { type BatchSimGameResult, type ScoreEntry } from "@/lib/api/analyticsTypes";
import {
  BattingTable,
  BasketballStats,
  GameShape,
  LineAnalysisDisplay,
  MLBStats,
  NFLStats,
  NHLStats,
  PitcherMatchup,
  ScoreBox,
  Section,
  MetaItem,
} from "./GameDetailModalParts";

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
              <PitcherMatchup
                homeTeam={game.home_team}
                awayTeam={game.away_team}
                homeSP={game.lineup_info.home_starter}
                awaySP={game.lineup_info.away_starter}
              />
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
