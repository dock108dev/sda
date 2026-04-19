"use client";

import { useMemo } from "react";
import type { NarrativeBlock, BlockMiniBox, BlockPlayerStat } from "@/lib/api/sportsAdmin/gameFlowTypes";
import { validateBlocksPreRender } from "@/lib/guardrails";
import { formatPeriodRange } from "@/lib/utils/periodLabels";
import styles from "./CollapsedGameFlow.module.css";

/**
 * Collapsed Game Flow
 *
 * The collapsed view is the PRIMARY product - complete and self-sufficient.
 *
 * May contain ONLY:
 * - Narrative blocks
 * - Embedded tweets
 *
 * Must NOT contain:
 * - Pregame tweets
 * - Postgame tweets
 * - Bulk social lists
 * - Hidden expandable sections
 *
 * Rendering rules:
 * - Narrative blocks define vertical rhythm
 * - Embedded tweets interleaved, never dominating
 * - Removing all tweets produces SAME narrative layout
 * - Total read time: 20-60 seconds
 *
 * Tweets act as reaction beats, NOT narrative drivers.
 */

interface CollapsedGameFlowProps {
  /** Narrative blocks to display */
  blocks: NarrativeBlock[];
  /** League code for period labels (NBA, NCAAB, NHL) */
  leagueCode?: string;
  /** Game ID for guardrail logging */
  gameId?: number;
  /** Home team name for score display */
  homeTeam?: string;
  /** Away team name for score display */
  awayTeam?: string;
  /** Whether to show debug information */
  showDebug?: boolean;
}

/**
 * Format semantic role for display.
 */
function formatRole(role: string): string {
  const roleLabels: Record<string, string> = {
    SETUP: "Opening",
    MOMENTUM_SHIFT: "Shift",
    RESPONSE: "Response",
    DECISION_POINT: "Decisive",
    RESOLUTION: "Final",
  };
  return roleLabels[role] || role;
}

/**
 * Get role badge color class.
 */
function getRoleBadgeClass(role: string): string {
  const roleColors: Record<string, string> = {
    SETUP: styles.roleSetup,
    MOMENTUM_SHIFT: styles.roleMomentum,
    RESPONSE: styles.roleResponse,
    DECISION_POINT: styles.roleDecision,
    RESOLUTION: styles.roleResolution,
  };
  return roleColors[role] || "";
}

/**
 * Mini Box Score Display
 *
 * Shows cumulative stats with segment deltas for top performers.
 */
function MiniBoxDisplay({ miniBox }: { miniBox: BlockMiniBox }) {
  const formatPlayer = (player: BlockPlayerStat, isHockey: boolean) => {
    const suffixes = new Set(["jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v", "vi"]);
    const words = player.name.split(" ");
    const last = words[words.length - 1];
    const lastName = words.length > 2 && suffixes.has(last.toLowerCase())
      ? `${words[words.length - 2]} ${last}`
      : last || player.name;

    if (isHockey) {
      const goals = player.goals || 0;
      const assists = player.assists || 0;
      const deltaG = player.deltaGoals || 0;
      const deltaA = player.deltaAssists || 0;

      if (goals === 0 && assists === 0) return null;

      const parts: string[] = [];
      if (goals > 0) {
        parts.push(deltaG > 0 ? `${goals}G (+${deltaG})` : `${goals}G`);
      }
      if (assists > 0) {
        parts.push(deltaA > 0 ? `${assists}A (+${deltaA})` : `${assists}A`);
      }

      return { name: lastName, stats: parts.join(", ") };
    } else {
      const pts = player.pts || 0;
      const deltaPts = player.deltaPts || 0;

      if (pts === 0) return null;

      const ptsStr = deltaPts > 0 ? `${pts} pts (+${deltaPts})` : `${pts} pts`;
      return { name: lastName, stats: ptsStr };
    }
  };

  const isHockey = miniBox.home.players.some(p => p.goals !== undefined);

  const homePlayers = miniBox.home.players
    .map(p => formatPlayer(p, isHockey))
    .filter(Boolean)
    .slice(0, 2);

  const awayPlayers = miniBox.away.players
    .map(p => formatPlayer(p, isHockey))
    .filter(Boolean)
    .slice(0, 2);

  if (homePlayers.length === 0 && awayPlayers.length === 0) {
    return null;
  }

  return (
    <div className={styles.miniBox}>
      <div className={styles.miniBoxTeam}>
        <div className={styles.miniBoxTeamName}>{miniBox.home.team}</div>
        <div className={styles.miniBoxPlayers}>
          {homePlayers.map((p, i) => (
            <div key={i} className={styles.miniBoxPlayer}>
              <span className={styles.miniBoxPlayerName}>{p!.name}:</span>
              <span className={styles.miniBoxStat}>{p!.stats}</span>
            </div>
          ))}
        </div>
      </div>
      <div className={styles.miniBoxTeam}>
        <div className={styles.miniBoxTeamName}>{miniBox.away.team}</div>
        <div className={styles.miniBoxPlayers}>
          {awayPlayers.map((p, i) => (
            <div key={i} className={styles.miniBoxPlayer}>
              <span className={styles.miniBoxPlayerName}>{p!.name}:</span>
              <span className={styles.miniBoxStat}>{p!.stats}</span>
            </div>
          ))}
        </div>
      </div>
      {miniBox.blockStars && miniBox.blockStars.length > 0 && (
        <div className={styles.blockStars}>
          <span className={styles.blockStarsLabel}>Stars:</span>
          {miniBox.blockStars.map((star, i) => (
            <span key={i} className={styles.blockStar}>{star}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Narrative Block Display
 *
 * Renders a single narrative block with its semantic role.
 * Optional embedded tweet displayed after the narrative.
 */
function BlockCard({
  block,
  leagueCode,
  homeTeam,
  awayTeam,
  showDebug,
}: {
  block: NarrativeBlock;
  leagueCode: string;
  homeTeam?: string;
  awayTeam?: string;
  showDebug?: boolean;
}) {
  const hasScoreChange =
    block.scoreBefore.home !== block.scoreAfter.home ||
    block.scoreBefore.away !== block.scoreAfter.away;

  const formatScore = (score: { home: number; away: number }) =>
    `${score.away}-${score.home}`;

  return (
    <div className={styles.blockCard}>
      {/* Block header with role badge */}
      <div className={styles.blockHeader}>
        <span className={`${styles.roleBadge} ${getRoleBadgeClass(block.role)}`}>
          {formatRole(block.role)}
        </span>
        {hasScoreChange && (
          <span className={styles.scoreChange}>
            {formatScore(block.scoreBefore)} → {formatScore(block.scoreAfter)}
          </span>
        )}
        {block.periodStart !== block.periodEnd ? (
          <span className={styles.periodRange}>
            {formatPeriodRange(block.periodStart, block.periodEnd, leagueCode)}
          </span>
        ) : (
          <span className={styles.periodBadge}>{formatPeriodRange(block.periodStart, block.periodEnd, leagueCode)}</span>
        )}
      </div>

      {/* Narrative text - the primary content */}
      <p className={styles.narrative}>{block.narrative || "No narrative"}</p>

      {/* Mini box score - cumulative stats with deltas */}
      {block.miniBox && <MiniBoxDisplay miniBox={block.miniBox} />}

      {/* Embedded social post indicator - optional, visually secondary */}
      {block.embeddedSocialPostId && (
        <div className={styles.embeddedTweet}>
          <span className={styles.tweetMeta}>Social post #{block.embeddedSocialPostId}</span>
        </div>
      )}

      {/* Debug info - only when enabled */}
      {showDebug && (
        <div className={styles.debugInfo}>
          <span>Block #{block.blockIndex}</span>
          <span>Moments: {block.momentIndices.join(", ")}</span>
          <span>Plays: {block.playIds.length}</span>
          <span>Key plays: {block.keyPlayIds.join(", ")}</span>
        </div>
      )}
    </div>
  );
}

/**
 * Main collapsed game flow component.
 *
 * Renders narrative blocks with optional embedded tweets.
 * This is the primary, self-sufficient view of the game story.
 */
export function CollapsedGameFlow({
  blocks,
  leagueCode = "NBA",
  gameId,
  homeTeam,
  awayTeam,
  showDebug = false,
}: CollapsedGameFlowProps) {
  // Run guardrail validation on every render
  // This ensures violations are immediately visible during development
  const guardrailResult = useMemo(
    () => validateBlocksPreRender(blocks, gameId ?? null),
    [blocks, gameId]
  );

  // Empty state - no blocks
  if (!blocks || blocks.length === 0) {
    return (
      <div className={styles.emptyState}>
        No story blocks available
      </div>
    );
  }

  // Count embedded tweets for summary
  const embeddedTweetCount = blocks.filter((b) => b.embeddedSocialPostId).length;

  // Calculate total word count
  const totalWords = blocks.reduce((sum, b) => {
    const narrativeWords = b.narrative?.split(/\s+/).length || 0;
    return sum + narrativeWords;
  }, 0);

  return (
    <div className={styles.container}>
      {/* Guardrail violation warning - visible in dev */}
      {!guardrailResult.passed && (
        <div className={styles.guardrailWarning}>
          <strong>Guardrail Violations:</strong>
          <ul>
            {guardrailResult.violations
              .filter((v) => v.severity === "error")
              .map((v, i) => (
                <li key={i}>{v.message}</li>
              ))}
          </ul>
        </div>
      )}

      {/* Summary line */}
      <div className={styles.summary}>
        {blocks.length} blocks · ~{totalWords} words
        {embeddedTweetCount > 0 && ` · ${embeddedTweetCount} embedded tweets`}
        {!guardrailResult.passed && " · ⚠️ VIOLATIONS"}
      </div>

      {/* Blocks list - vertical flow */}
      <div className={styles.blocksList}>
        {blocks.map((block) => (
          <BlockCard
            key={block.blockIndex}
            block={block}
            leagueCode={leagueCode}
            homeTeam={homeTeam}
            awayTeam={awayTeam}
            showDebug={showDebug}
          />
        ))}
      </div>
    </div>
  );
}

export default CollapsedGameFlow;
