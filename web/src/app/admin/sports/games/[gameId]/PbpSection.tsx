"use client";

import { useMemo, useState } from "react";
import type { AdminGameDetail } from "@/lib/api/sportsAdmin";
import styles from "./styles.module.css";

/**
 * Get period label based on league format.
 * - NBA: Q1, Q2, Q3, Q4, OT1, OT2...
 * - NHL: P1, P2, P3, OT, SO
 * - NCAAB: 1st Half, 2nd Half, OT1, OT2...
 */
const getPeriodLabel = (period: number, leagueCode?: string) => {
  if (leagueCode === "MLB") {
    const ordinals: Record<number, string> = {1: "1st", 2: "2nd", 3: "3rd"};
    return ordinals[period] ?? `${period}th`;
  }
  if (leagueCode === "NCAAB") {
    // NCAAB uses halves
    if (period === 1) return "1st Half";
    if (period === 2) return "2nd Half";
    return `OT${period - 2}`;
  }
  if (leagueCode === "NHL") {
    if (period <= 3) return `P${period}`;
    if (period === 4) return "OT";
    return "SO";
  }
  // Default: NBA-style quarters
  if (period <= 4) return `Q${period}`;
  return `OT${period - 4}`;
};

function TierBadge({ tier }: { tier: number | null }) {
  if (tier === null) return <span>—</span>;
  const tierClass =
    tier === 1 ? styles.tierBadge1 :
    tier === 2 ? styles.tierBadge2 :
    styles.tierBadge3;
  return <span className={`${styles.tierBadge} ${tierClass}`}>T{tier}</span>;
}

type CollapsedGroup = {
  type: "group";
  plays: AdminGameDetail["plays"];
  playTypes: string[];
  scoreRange: string;
};

type DisplayRow = { type: "play"; play: AdminGameDetail["plays"][0] } | CollapsedGroup;

type PbpSectionProps = {
  plays: AdminGameDetail["plays"];
  groupedPlays: AdminGameDetail["groupedPlays"];
  leagueCode?: string;
};

export function PbpSection({ plays, groupedPlays, leagueCode }: PbpSectionProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedQuarter, setSelectedQuarter] = useState<number | null>(null);
  const [collapseRoutine, setCollapseRoutine] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<number>>(new Set());

  const quarters = useMemo(() => {
    const qs = [...new Set(plays.map((p) => p.quarter).filter((q) => q !== null))] as number[];
    return qs.sort((a, b) => a - b);
  }, [plays]);

  const effectiveQuarter = useMemo(() => {
    if (quarters.length === 0) return null;
    if (selectedQuarter === null) return quarters[0];
    return quarters.includes(selectedQuarter) ? selectedQuarter : quarters[0];
  }, [quarters, selectedQuarter]);

  const filteredPlays = useMemo(() => {
    if (effectiveQuarter === null) return plays;
    return plays.filter((p) => p.quarter === effectiveQuarter);
  }, [plays, effectiveQuarter]);

  // Build grouped indices from API groupedPlays
  const groupedIndexSet = useMemo(() => {
    if (!groupedPlays) return new Set<number>();
    return new Set(groupedPlays.flatMap((g) => g.playIndices));
  }, [groupedPlays]);

  // Build display rows: collapse consecutive Tier 3 plays when toggle is on
  const displayRows = useMemo((): DisplayRow[] => {
    if (!collapseRoutine) {
      return filteredPlays.map((play) => ({ type: "play" as const, play }));
    }

    const rows: DisplayRow[] = [];
    let i = 0;
    while (i < filteredPlays.length) {
      const play = filteredPlays[i];
      if (play.tier === 3 || (play.tier === null && groupedIndexSet.has(play.playIndex))) {
        // Collect consecutive tier-3/grouped plays
        const group: AdminGameDetail["plays"] = [];
        while (
          i < filteredPlays.length &&
          (filteredPlays[i].tier === 3 || (filteredPlays[i].tier === null && groupedIndexSet.has(filteredPlays[i].playIndex)))
        ) {
          group.push(filteredPlays[i]);
          i++;
        }
        if (group.length >= 2) {
          const playTypes = [...new Set(group.map((p) => p.playType).filter(Boolean))] as string[];
          const scores = group.filter((p) => p.score != null);
          const firstScore = scores[0];
          const lastScore = scores[scores.length - 1];
          const scoreRange =
            firstScore?.score && lastScore?.score
              ? `${firstScore.score.away}-${firstScore.score.home} → ${lastScore.score.away}-${lastScore.score.home}`
              : "—";
          rows.push({ type: "group", plays: group, playTypes, scoreRange });
        } else {
          // Single tier-3 play, show normally
          rows.push({ type: "play", play: group[0] });
        }
      } else {
        rows.push({ type: "play", play });
        i++;
      }
    }
    return rows;
  }, [filteredPlays, collapseRoutine, groupedIndexSet]);

  const toggleGroup = (idx: number) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div className={styles.card}>
      <button
        type="button"
        className={styles.collapsibleHeader}
        onClick={() => setIsOpen(!isOpen)}
      >
        <h2>Play-by-Play</h2>
        <span className={styles.chevron}>{isOpen ? "▼" : "▶"}</span>
      </button>
      {isOpen && (
        <div className={styles.collapsibleContent}>
          {plays.length === 0 ? (
            <div style={{ color: "#475569" }}>No play-by-play data found for this game.</div>
          ) : (
            <>
              <div className={styles.quarterTabs}>
                {quarters.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className={`${styles.quarterTab} ${effectiveQuarter === q ? styles.quarterTabActive : ""}`}
                    onClick={() => setSelectedQuarter(q)}
                  >
                    {getPeriodLabel(q, leagueCode)}
                    <span className={styles.quarterCount}>
                      {plays.filter((p) => p.quarter === q).length}
                    </span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                className={`${styles.collapseToggle} ${collapseRoutine ? styles.collapseToggleActive : ""}`}
                onClick={() => {
                  setCollapseRoutine(!collapseRoutine);
                  setExpandedGroups(new Set());
                }}
              >
                {collapseRoutine ? "Showing all plays" : "Collapse routine plays"}
              </button>
              <div className={styles.pbpContainer}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th><span className={styles.fieldLabel} title="API field: gameClock">Time</span></th>
                      <th><span className={styles.fieldLabel} title="API field: teamAbbreviation">Team</span></th>
                      <th>Player</th>
                      <th>Description</th>
                      <th><span className={styles.fieldLabel} title="API field: score.away / score.home">Score</span></th>
                      <th><span className={styles.fieldLabel} title="API field: tier">Tier</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayRows.map((row, idx) => {
                      if (row.type === "play") {
                        const play = row.play;
                        return (
                          <tr key={`play-${play.playIndex}-${idx}`}>
                            <td>{play.gameClock ?? "—"}</td>
                            <td>{play.teamAbbreviation ?? "—"}</td>
                            <td>{play.playerName ?? "—"}</td>
                            <td className={styles.pbpDescription}>{play.description ?? "—"}</td>
                            <td>
                              {play.score != null
                                ? `${play.score.away}-${play.score.home}`
                                : "—"}
                            </td>
                            <td><TierBadge tier={play.tier} /></td>
                          </tr>
                        );
                      }

                      // Collapsed group row
                      const isExpanded = expandedGroups.has(idx);
                      return (
                        <tr key={`group-${idx}`}>
                          <td colSpan={6} style={{ padding: 0 }}>
                            <div
                              className={styles.tier3GroupRow}
                              onClick={() => toggleGroup(idx)}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleGroup(idx); } }}
                            >
                              <div className={styles.tier3GroupSummary} style={{ padding: "0.5rem 0.65rem" }}>
                                {isExpanded ? "▼" : "▶"}{" "}
                                {row.plays.length} routine plays
                                {row.playTypes.length > 0 && ` (${row.playTypes.join(", ")})`}
                                {" · "}Score: {row.scoreRange}
                              </div>
                            </div>
                            {isExpanded && (
                              <table className={styles.table} style={{ margin: 0 }}>
                                <tbody>
                                  {row.plays.map((play, pIdx) => (
                                    <tr key={`group-${idx}-play-${play.playIndex}-${pIdx}`}>
                                      <td>{play.gameClock ?? "—"}</td>
                                      <td>{play.teamAbbreviation ?? "—"}</td>
                                      <td>{play.playerName ?? "—"}</td>
                                      <td className={styles.pbpDescription}>{play.description ?? "—"}</td>
                                      <td>
                                        {play.score != null
                                          ? `${play.score.away}-${play.score.home}`
                                          : "—"}
                                      </td>
                                      <td><TierBadge tier={play.tier} /></td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
