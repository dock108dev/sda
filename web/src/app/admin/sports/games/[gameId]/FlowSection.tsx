"use client";

/**
 * Game Flow Section — Admin debugging view.
 *
 * Shows narrative blocks (primary) or raw moments (when blocks are absent).
 * Consumer-facing components live in @/components/gameflow/.
 */

import { useCallback, useEffect, useState } from "react";
import { fetchGameFlow } from "@/lib/api/sportsAdmin";
import type { GameFlowResponse, GameFlowMoment, GameFlowPlay, MomentBoxScore, MomentPlayerStat, NarrativeBlock, BlockMiniBox, BlockPlayerStat } from "@/lib/api/sportsAdmin/gameFlowTypes";
import { CollapsibleSection } from "./CollapsibleSection";
import { formatPeriodLabel, formatPeriodRange } from "@/lib/utils/periodLabels";
import styles from "./styles.module.css";

type FlowSectionProps = {
  gameId: number;
  hasFlow: boolean;
  leagueCode: string;
};

type MomentCardProps = {
  moment: GameFlowMoment;
  momentIndex: number;
  plays: GameFlowPlay[];
  leagueCode: string;
};

function formatPlayerStats(player: MomentPlayerStat): string {
  const parts: string[] = [];
  // Basketball stats
  if (player.pts != null && player.pts > 0) parts.push(`${player.pts} pts`);
  if (player.reb != null && player.reb > 0) parts.push(`${player.reb} reb`);
  if (player.ast != null && player.ast > 0) parts.push(`${player.ast} ast`);
  if (player["3pm"] != null && player["3pm"] > 0) parts.push(`${player["3pm"]} 3pm`);
  // Hockey stats
  if (player.goals != null && player.goals > 0) parts.push(`${player.goals} G`);
  if (player.assists != null && player.assists > 0) parts.push(`${player.assists} A`);
  if (player.sog != null && player.sog > 0) parts.push(`${player.sog} SOG`);
  // Baseball stats
  if (player.runs != null && player.runs > 0) parts.push(`${player.runs} R`);
  if (player.hits != null && player.hits > 0) parts.push(`${player.hits} H`);
  if (player.rbi != null && player.rbi > 0) parts.push(`${player.rbi} RBI`);
  if (player.hr != null && player.hr > 0) parts.push(`${player.hr} HR`);
  return parts.join(", ");
}

function MiniBoxScore({ boxScore }: { boxScore: MomentBoxScore }) {
  const hasPlayers = boxScore.home.players.length > 0 || boxScore.away.players.length > 0;

  return (
    <div className={styles.miniBoxScore}>
      <div className={styles.miniBoxScoreTeams}>
        <div className={styles.miniBoxScoreTeam}>
          <div className={styles.miniBoxScoreHeader}>
            <span className={styles.miniBoxScoreTeamName}>{boxScore.away.team}</span>
            <span className={styles.miniBoxScoreScore}>{boxScore.away.score}</span>
          </div>
          {hasPlayers && boxScore.away.players.slice(0, 3).map((player, i) => (
            <div key={i} className={styles.miniBoxScorePlayer}>
              <span className={styles.miniBoxScorePlayerName}>{player.name}</span>
              <span className={styles.miniBoxScorePlayerStats}>{formatPlayerStats(player)}</span>
            </div>
          ))}
          {boxScore.away.goalie && (
            <div className={styles.miniBoxScorePlayer}>
              <span className={styles.miniBoxScorePlayerName}>{boxScore.away.goalie.name}</span>
              <span className={styles.miniBoxScorePlayerStats}>
                {boxScore.away.goalie.saves} SV, {boxScore.away.goalie.ga} GA
              </span>
            </div>
          )}
        </div>
        <div className={styles.miniBoxScoreTeam}>
          <div className={styles.miniBoxScoreHeader}>
            <span className={styles.miniBoxScoreTeamName}>{boxScore.home.team}</span>
            <span className={styles.miniBoxScoreScore}>{boxScore.home.score}</span>
          </div>
          {hasPlayers && boxScore.home.players.slice(0, 3).map((player, i) => (
            <div key={i} className={styles.miniBoxScorePlayer}>
              <span className={styles.miniBoxScorePlayerName}>{player.name}</span>
              <span className={styles.miniBoxScorePlayerStats}>{formatPlayerStats(player)}</span>
            </div>
          ))}
          {boxScore.home.goalie && (
            <div className={styles.miniBoxScorePlayer}>
              <span className={styles.miniBoxScorePlayerName}>{boxScore.home.goalie.name}</span>
              <span className={styles.miniBoxScorePlayerStats}>
                {boxScore.home.goalie.saves} SV, {boxScore.home.goalie.ga} GA
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MomentCard({ moment, momentIndex, plays, leagueCode }: MomentCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Get plays for this moment
  const momentPlays = plays.filter((p) => moment.playIds.includes(p.playId));
  const explicitPlayIds = new Set(moment.explicitlyNarratedPlayIds);

  // Format score display
  const formatScore = (score: number[]) => {
    if (score.length >= 2) {
      return `${score[0]}-${score[1]}`;
    }
    return "—";
  };

  // Check if score changed
  const scoreChanged =
    moment.scoreBefore[0] !== moment.scoreAfter[0] ||
    moment.scoreBefore[1] !== moment.scoreAfter[1];

  return (
    <div className={styles.momentCard}>
      <div className={styles.momentHeader}>
        <div className={styles.momentMeta}>
          <span className={styles.momentIndex}>#{momentIndex + 1}</span>
          <span className={styles.momentPeriod}>{formatPeriodLabel(moment.period, leagueCode)}</span>
          {moment.startClock && (
            <span className={styles.momentClock}>
              {moment.startClock}
              {moment.endClock && moment.endClock !== moment.startClock && ` → ${moment.endClock}`}
            </span>
          )}
          {scoreChanged && (
            <span className={styles.momentScoreChange}>
              {formatScore(moment.scoreBefore)} → {formatScore(moment.scoreAfter)}
            </span>
          )}
        </div>
        <button
          type="button"
          className={styles.expandButton}
          onClick={() => setIsExpanded(!isExpanded)}
          aria-expanded={isExpanded}
        >
          {isExpanded ? "Hide plays" : `Show ${momentPlays.length} plays`}
        </button>
      </div>

      <div className={styles.momentNarrative}>{moment.narrative}</div>

      {moment.cumulativeBoxScore && (
        <MiniBoxScore boxScore={moment.cumulativeBoxScore} />
      )}

      {isExpanded && (
        <div className={styles.momentPlays}>
          <table className={styles.playsTable}>
            <thead>
              <tr>
                <th>Clock</th>
                <th>Type</th>
                <th>Description</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {momentPlays.map((play) => {
                const isExplicit = explicitPlayIds.has(play.playId);
                return (
                  <tr
                    key={play.playId}
                    className={isExplicit ? styles.explicitPlay : undefined}
                  >
                    <td>{play.clock ?? "—"}</td>
                    <td>{play.playType ?? "—"}</td>
                    <td>{play.description ?? "—"}</td>
                    <td>
                      {play.homeScore !== null && play.awayScore !== null
                        ? `${play.awayScore}-${play.homeScore}`
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className={styles.playLegend}>
            <span className={styles.explicitIndicator} /> = Explicitly narrated play
          </div>
        </div>
      )}
    </div>
  );
}

function BlockMiniBoxDisplay({ miniBox }: { miniBox: BlockMiniBox }) {
  // Detect sport by checking for stat keys
  const isHockey = miniBox.home.players.some(p => p.goals !== undefined);
  const isBaseball = miniBox.home.players.some(p => p.runs !== undefined || p.rbi !== undefined);

  const fmt = (val: number | undefined, delta: number | undefined, label: string) => {
    if (!val) return null;
    return delta ? `${val} ${label} (+${delta})` : `${val} ${label}`;
  };

  const formatPlayer = (p: BlockPlayerStat) => {
    const suffixes = new Set(["jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v", "vi"]);
    const words = p.name.split(" ");
    const last = words[words.length - 1];
    const lastName = words.length > 2 && suffixes.has(last.toLowerCase())
      ? `${words[words.length - 2]} ${last}`
      : last || p.name;
    if (isBaseball) {
      const parts = [
        fmt(p.runs, p.deltaRuns, "R"),
        fmt(p.hits, p.deltaHits, "H"),
        fmt(p.rbi, p.deltaRbi, "RBI"),
        p.hr ? `${p.hr} HR` : null,
      ].filter(Boolean);
      return parts.length ? { name: lastName, stats: parts.join(", ") } : null;
    }
    if (isHockey) {
      const parts = [
        fmt(p.goals, p.deltaGoals, "G"),
        fmt(p.assists, p.deltaAssists, "A"),
        p.sog ? `${p.sog} SOG` : null,
      ].filter(Boolean);
      return parts.length ? { name: lastName, stats: parts.join(", ") } : null;
    }
    const parts = [
      fmt(p.pts, p.deltaPts, "pts"),
      fmt(p.reb, p.deltaReb, "reb"),
      fmt(p.ast, p.deltaAst, "ast"),
    ].filter(Boolean);
    return parts.length ? { name: lastName, stats: parts.join(", ") } : null;
  };

  const home = miniBox.home.players.map(formatPlayer).filter(Boolean).slice(0, 3);
  const away = miniBox.away.players.map(formatPlayer).filter(Boolean).slice(0, 3);
  if (!home.length && !away.length) return null;

  return (
    <div className={styles.miniBoxScore}>
      <div className={styles.miniBoxScoreTeams}>
        {/* Away team first (matches score display convention) */}
        <div className={styles.miniBoxScoreTeam}>
          <div className={styles.miniBoxScoreHeader}>
            <span className={styles.miniBoxScoreTeamName}>{miniBox.away.team}</span>
          </div>
          {away.map((p, i) => (
            <div key={i} className={styles.miniBoxScorePlayer}>
              <span className={styles.miniBoxScorePlayerName}>{p!.name}</span>
              <span className={styles.miniBoxScorePlayerStats}>{p!.stats}</span>
            </div>
          ))}
        </div>
        <div className={styles.miniBoxScoreTeam}>
          <div className={styles.miniBoxScoreHeader}>
            <span className={styles.miniBoxScoreTeamName}>{miniBox.home.team}</span>
          </div>
          {home.map((p, i) => (
            <div key={i} className={styles.miniBoxScorePlayer}>
              <span className={styles.miniBoxScorePlayerName}>{p!.name}</span>
              <span className={styles.miniBoxScorePlayerStats}>{p!.stats}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function FlowSection({ gameId, hasFlow, leagueCode }: FlowSectionProps) {
  const [story, setStory] = useState<GameFlowResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadFlow = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGameFlow(gameId);
      setStory(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load game flow");
    } finally {
      setLoading(false);
    }
  }, [gameId]);

  useEffect(() => {
    if (hasFlow) {
      loadFlow();
    }
  }, [hasFlow, loadFlow]);

  // Don't render section if no flow
  if (!hasFlow) {
    return null;
  }

  return (
    <CollapsibleSection title="Game Flow" defaultOpen={true}>
      {loading && <div className={styles.subtle}>Loading game flow...</div>}

      {error && <div className={styles.storyError}>Error: {error}</div>}

      {!loading && !error && !story && (
        <div className={styles.subtle}>No game flow found.</div>
      )}

      {story && (
        <div className={styles.storyContainer}>
          {!story.validationPassed && story.validationErrors.length > 0 && (
            <div className={styles.validationWarning}>
              <strong>Validation issues:</strong>
              <ul>
                {story.validationErrors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}

          {/* PRIMARY: Narrative blocks with AI-generated text */}
          {story.blocks && story.blocks.length > 0 && (
            <>
              <div className={styles.storySummary}>
                {story.blocks.length} blocks · {story.totalWords ?? 0} words
              </div>
              <div className={styles.momentsList}>
                {story.blocks.map((block) => (
                  <div key={block.blockIndex} className={styles.momentCard}>
                    <div className={styles.momentHeader}>
                      <div className={styles.momentMeta}>
                        <span className={styles.momentIndex}>#{block.blockIndex + 1}</span>
                        <span className={styles.momentPeriod} style={{
                          background: block.role === "SETUP" ? "#e0f2fe" :
                                     block.role === "MOMENTUM_SHIFT" ? "#fef3c7" :
                                     block.role === "RESOLUTION" ? "#dcfce7" : "#f3e8ff",
                          color: block.role === "SETUP" ? "#0369a1" :
                                 block.role === "MOMENTUM_SHIFT" ? "#b45309" :
                                 block.role === "RESOLUTION" ? "#166534" : "#7e22ce"
                        }}>{block.role}</span>
                        <span className={styles.momentClock}>
                          {formatPeriodRange(block.periodStart, block.periodEnd, leagueCode)}
                        </span>
                        <span className={styles.momentScoreChange}>
                          {block.scoreBefore[0]}-{block.scoreBefore[1]} → {block.scoreAfter[0]}-{block.scoreAfter[1]}
                        </span>
                      </div>
                    </div>
                    <div className={styles.momentNarrative}>
                      {block.narrative || <span style={{ color: "#94a3b8", fontStyle: "italic" }}>No narrative</span>}
                    </div>
                    {block.miniBox && <BlockMiniBoxDisplay miniBox={block.miniBox} />}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Raw moments view (when blocks are absent) */}
          {(!story.blocks || story.blocks.length === 0) && (
            <>
              <div className={styles.storySummary}>
                {story.flow.moments.length} moments · {story.plays.length} plays
                <span style={{ color: "#94a3b8", marginLeft: "0.5rem" }}>(no blocks)</span>
              </div>
              <div className={styles.momentsList}>
                {story.flow.moments.map((moment, idx) => (
                  <MomentCard
                    key={idx}
                    moment={moment}
                    momentIndex={idx}
                    plays={story.plays}
                    leagueCode={leagueCode}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </CollapsibleSection>
  );
}
