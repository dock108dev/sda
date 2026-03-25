"use client";

import { AdminCard } from "@/components/admin";
import type { SimulationResult } from "@/lib/api/analytics";
import { ScoreDistributionChart, PAProbabilitiesChart } from "../charts";
import styles from "../analytics.module.css";
import { SimulationInfoBanner } from "./SimulationInfoBanner";
import { DataFreshnessDisplay } from "./DataFreshnessDisplay";
import { PitcherProfileCard, MetricsTable } from "./PitcherProfileCard";
import { EdgeAnalysis } from "./EdgeAnalysis";

/**
 * Renders all simulation result cards — win probability, edge analysis,
 * sportsbook comparison, pitch-level probabilities, pitching analytics,
 * score distribution, etc.
 */
export function SimulationResults({
  result,
  homeMoneyline,
  awayMoneyline,
  sport = "mlb",
}: {
  result: SimulationResult;
  homeMoneyline: string;
  awayMoneyline: string;
  sport?: string;
}) {
  return (
    <div className={styles.resultsSection}>
      <AdminCard title="Win Probability">
        <div className={styles.statsRow}>
          <div className={styles.statBox}>
            <div className={styles.statValue}>{(result.home_win_probability * 100).toFixed(1)}%</div>
            <div className={styles.statLabel}>{result.home_team} (Home)</div>
          </div>
          <div className={styles.statBox}>
            <div className={styles.statValue}>{(result.away_win_probability * 100).toFixed(1)}%</div>
            <div className={styles.statLabel}>{result.away_team} (Away)</div>
          </div>
        </div>
        <div className={styles.probBar}>
          <span className={styles.probLabel}>{result.home_team}</span>
          <div className={styles.probTrack}>
            <div className={styles.probFill} style={{ width: `${result.home_win_probability * 100}%` }} />
          </div>
          <span className={styles.probLabel} style={{ textAlign: "right" }}>{result.away_team}</span>
        </div>
        {!!result.profile_meta?.lineup_mode && (
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
            Lineup-aware simulation with per-batter matchup probabilities
          </p>
        )}
      </AdminCard>

      {result.simulation_info && (
        <SimulationInfoBanner info={result.simulation_info} />
      )}

      {result.profile_meta && (
        <EdgeAnalysis
          profileMeta={result.profile_meta}
          homeTeam={result.home_team}
          awayTeam={result.away_team}
          homeWP={result.home_win_probability}
        />
      )}

      {/* Sportsbook comparison — only when moneylines were provided */}
      {result.sportsbook_comparison && homeMoneyline && awayMoneyline && (() => {
        const toImpliedProb = (ml: number) => {
          if (ml > 0) return 100 / (ml + 100);
          return Math.abs(ml) / (Math.abs(ml) + 100);
        };
        const homeImplied = toImpliedProb(parseFloat(homeMoneyline));
        const awayImplied = toImpliedProb(parseFloat(awayMoneyline));
        const homeEdge = result.home_win_probability - homeImplied;
        const awayEdge = result.away_win_probability - awayImplied;
        return (
          <AdminCard title="Sportsbook Comparison" subtitle="Sim vs implied probability from moneylines">
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(homeImplied * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>{result.home_team} Implied</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(awayImplied * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>{result.away_team} Implied</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue} style={{ color: homeEdge > 0 ? "#16a34a" : "#dc2626" }}>
                  {homeEdge > 0 ? "+" : ""}{(homeEdge * 100).toFixed(1)}%
                </div>
                <div className={styles.statLabel}>{result.home_team} Edge</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue} style={{ color: awayEdge > 0 ? "#16a34a" : "#dc2626" }}>
                  {awayEdge > 0 ? "+" : ""}{(awayEdge * 100).toFixed(1)}%
                </div>
                <div className={styles.statLabel}>{result.away_team} Edge</div>
              </div>
            </div>
          </AdminCard>
        );
      })()}

      {sport === "mlb" && result.home_pa_probabilities && result.away_pa_probabilities && (
        <AdminCard title="Pitch-Level Probabilities" subtitle="From rolling 30-game profiles">
          <PAProbabilitiesChart
            homeProbs={result.home_pa_probabilities}
            awayProbs={result.away_pa_probabilities}
            homeLabel={result.home_team}
            awayLabel={result.away_team}
          />
          {result.profile_meta?.data_freshness && (
            <DataFreshnessDisplay
              freshness={result.profile_meta.data_freshness}
              homeLabel={result.home_team}
              awayLabel={result.away_team}
            />
          )}
        </AdminCard>
      )}

      {sport === "mlb" && result.profile_meta?.home_pitcher && result.profile_meta?.away_pitcher && (
        <AdminCard title="Pitching Analytics" subtitle="Starter profiles used in simulation">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
            <PitcherProfileCard
              label={`${result.home_team} SP`}
              pitcher={result.profile_meta.home_pitcher}
            />
            <PitcherProfileCard
              label={`${result.away_team} SP`}
              pitcher={result.profile_meta.away_pitcher}
            />
          </div>
          {(result.profile_meta.home_bullpen || result.profile_meta.away_bullpen) && (
            <div style={{ marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid var(--border)" }}>
              <div style={{ fontSize: "0.8rem", fontWeight: 500, marginBottom: "0.5rem", color: "var(--text-muted)" }}>
                Bullpen Profiles (derived from team pitching)
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
                {result.profile_meta.home_bullpen && (
                  <MetricsTable metrics={result.profile_meta.home_bullpen} label={`${result.home_team} Bullpen`} />
                )}
                {result.profile_meta.away_bullpen && (
                  <MetricsTable metrics={result.profile_meta.away_bullpen} label={`${result.away_team} Bullpen`} />
                )}
              </div>
            </div>
          )}
        </AdminCard>
      )}

      {result.profile_meta && !result.profile_meta.has_profiles && (
        <AdminCard title="Profile Status">
          <p style={{ color: "#ef4444", fontSize: "0.9rem" }}>
            Could not load team profiles. Using league-average defaults.
          </p>
        </AdminCard>
      )}

      <AdminCard title="Average Score" subtitle={`Based on ${result.iterations.toLocaleString()} simulations`}>
        <div className={styles.statsRow}>
          <div className={styles.statBox}>
            <div className={styles.statValue}>{result.average_home_score}</div>
            <div className={styles.statLabel}>{result.home_team} Avg</div>
          </div>
          <div className={styles.statBox}>
            <div className={styles.statValue}>{result.average_away_score}</div>
            <div className={styles.statLabel}>{result.away_team} Avg</div>
          </div>
          <div className={styles.statBox}>
            <div className={styles.statValue}>{result.average_total}</div>
            <div className={styles.statLabel}>Avg Total</div>
          </div>
          <div className={styles.statBox}>
            <div className={styles.statValue}>{result.median_total}</div>
            <div className={styles.statLabel}>Median Total</div>
          </div>
        </div>
      </AdminCard>

      {result.most_common_scores && result.most_common_scores.length > 0 && (
        <AdminCard title="Most Common Scores">
          <ScoreDistributionChart data={result.most_common_scores} />
        </AdminCard>
      )}
    </div>
  );
}
