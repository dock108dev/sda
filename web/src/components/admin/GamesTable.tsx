"use client";

import Link from "next/link";
import { type GameSummary } from "@/lib/api/sportsAdmin";
import { ROUTES } from "@/lib/constants/routes";
import { deriveDataStatus, type DataField } from "@/lib/utils/dataStatus";
import { DataStatusIndicator } from "./DataStatusIndicator";
import styles from "./GamesTable.module.css";

interface GamesTableProps {
  games: GameSummary[];
  detailLink?: (id: number | string) => string;
  showCompleteness?: boolean;
}

/** Map of data field → accessor on GameSummary for the boolean + optional timestamp */
function getFieldStatus(game: GameSummary, field: DataField) {
  const tsMap: Record<DataField, string | null | undefined> = {
    boxscore: game.lastScrapedAt,
    playerStats: game.lastScrapedAt,
    odds: game.lastOddsAt,
    social: game.lastSocialAt,
    pbp: game.lastPbpAt,
    flow: game.lastScrapedAt,
    advancedStats: game.lastAdvancedStatsAt,
  };

  const hasMap: Record<DataField, boolean> = {
    boxscore: game.hasBoxscore,
    playerStats: game.hasPlayerStats,
    odds: game.hasOdds,
    social: game.hasSocial,
    pbp: game.hasPbp,
    flow: game.hasFlow,
    advancedStats: game.hasAdvancedStats,
  };

  return deriveDataStatus(field, hasMap[field], game.gameDate, tsMap[field]);
}

/**
 * Table component for displaying game summaries.
 * Shows game metadata and structured data status indicators.
 */
export function GamesTable({ games, detailLink = ROUTES.SPORTS_GAME, showCompleteness = true }: GamesTableProps) {
  return (
    <>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>ID</th>
            <th>Date</th>
            <th>League</th>
            <th>Teams</th>
            {showCompleteness && (
              <>
                <th>Boxscore</th>
                <th>Players</th>
                <th>Odds</th>
                <th>Social</th>
                <th>PBP</th>
                <th>Flow</th>
                <th>Adv Stats</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {games.length === 0 ? (
            <tr>
                <td colSpan={showCompleteness ? 11 : 4} className={styles.emptyCell}>
                No games found
              </td>
            </tr>
          ) : (
            games.map((game) => {
              const gameId = game.id;
              const hasValidId = gameId !== undefined && gameId !== null;
              const idContent = hasValidId ? (
                <Link href={detailLink(gameId)} className={styles.link}>
                  {gameId}
                  </Link>
              ) : (
                "—"
              );

              return (
              <tr key={gameId ?? `${game.awayTeam}-${game.homeTeam}-${game.gameDate}`}>
                <td>{idContent}</td>
                <td>{new Date(game.gameDate).toLocaleString()}</td>
                <td>{game.leagueCode}</td>
                <td>
                  {game.awayTeam} @ {game.homeTeam}
                </td>
                {showCompleteness && (
                  <>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "boxscore")} />
                    </td>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "playerStats")} />
                    </td>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "odds")} />
                    </td>
                    <td>
                      <DataStatusIndicator
                        status={getFieldStatus(game, "social")}
                        count={game.socialPostCount}
                      />
                    </td>
                    <td>
                      <DataStatusIndicator
                        status={getFieldStatus(game, "pbp")}
                        count={game.playCount}
                      />
                    </td>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "flow")} />
                    </td>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "advancedStats")} />
                    </td>
                  </>
                )}
              </tr>
            )})
          )}
        </tbody>
      </table>
    </>
  );
}
