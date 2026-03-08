"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./styles.module.css";
import {
  fetchLiveGames,
  fetchFairbetLiveOdds,
  formatOdds,
  formatSelectionKey,
  formatMarketKey,
  formatMarketCategory,
  formatEv,
  getEvColor,
  getBestOdds,
  trueProbToAmerican,
  formatDisabledReason,
  type BetDefinition,
  type FairbetLiveResponse,
  type LiveGameInfo,
} from "@/lib/api/fairbet";
import { FAIRBET_LEAGUES } from "@/lib/constants/sports";
import { DerivationContent } from "../odds/DerivationContent";
import { formatGameDate, formatLastSync, formatLineValue } from "../odds/helpers";

const LEAGUES = FAIRBET_LEAGUES;
const REFRESH_INTERVAL = 15_000;

const SORT_OPTIONS = [
  { value: "ev", label: "Best EV" },
  { value: "market", label: "Market" },
];

interface GameLiveData {
  game: LiveGameInfo;
  data: FairbetLiveResponse | null;
  loading: boolean;
  error: string | null;
}

// Shared bet card (matches pregame BetCard)
function BetCard({
  bet,
  idx,
  openDerivation,
  setOpenDerivation,
  derivationRef,
}: {
  bet: BetDefinition;
  idx: string;
  openDerivation: string | null;
  setOpenDerivation: (idx: string | null) => void;
  derivationRef: React.RefObject<HTMLDivElement | null>;
}) {
  const bestBook = getBestOdds(bet.books);
  const bestBookEv = bestBook != null ? (bestBook.display_ev ?? bestBook.ev_percent) : null;
  const bestBookHasPositiveEv = bestBook != null && bestBookEv != null && bestBookEv > 0;

  return (
    <div className={styles.betCard}>
      <div className={styles.betHeader}>
        <div className={styles.betHeaderLeft}>
          {bet.market_category && bet.market_category !== "mainline" && (
            <span className={styles.categoryBadge}>
              {formatMarketCategory(bet.market_category)}
            </span>
          )}
        </div>
        <span className={styles.gameDate}>
          {bet.game_date ? formatGameDate(bet.game_date) : ""}
        </span>
      </div>

      {bet.player_name && (
        <div className={styles.playerName}>{bet.player_name}</div>
      )}

      <div className={styles.betType}>
        <span className={styles.marketType}>
          {formatMarketKey(bet.market_key)}
        </span>
        <span className={styles.selection}>
          {formatSelectionKey(bet.selection_key)}
          {formatLineValue(bet.line_value, bet.market_key) && (
            <span className={styles.line}>
              {" "}
              {formatLineValue(bet.line_value, bet.market_key)}
            </span>
          )}
        </span>
      </div>

      <div className={styles.booksGrid}>
        {bet.true_prob !== null && bet.true_prob !== undefined ? (
          <div
            className={`${styles.bookOdds} ${styles.fairOddsCard} ${styles.fairOddsClickable}`}
            onClick={() => setOpenDerivation(openDerivation === idx ? null : idx)}
            ref={openDerivation === idx ? derivationRef : undefined}
          >
            <span className={styles.bookName}>Fair</span>
            <span className={styles.bookPrice}>
              {formatOdds(trueProbToAmerican(bet.true_prob))}
            </span>
            <span className={styles.fairProb}>
              {(bet.true_prob * 100).toFixed(1)}%
            </span>
            {bet.ev_confidence_tier && (
              <span className={`${styles.confidenceBadge} ${
                styles[`confidence_${bet.ev_confidence_tier}` as keyof typeof styles] ?? ""
              }`}>
                {bet.ev_confidence_tier}
              </span>
            )}
            {openDerivation === idx &&
              ((bet.reference_price !== null &&
                bet.opposite_reference_price !== null) ||
                bet.ev_method === "median_consensus") && (
                <DerivationContent
                  referencePrice={bet.reference_price}
                  oppositeReferencePrice={bet.opposite_reference_price}
                  trueProb={bet.true_prob}
                  evMethod={bet.ev_method}
                  estimatedSharpPrice={bet.estimated_sharp_price}
                  extrapolationRefLine={bet.extrapolation_ref_line}
                  extrapolationDistance={bet.extrapolation_distance}
                  perBookFairProbs={bet.per_book_fair_probs}
                  consensusIqr={bet.consensus_iqr}
                  consensusBookCount={bet.consensus_book_count}
                />
              )}
          </div>
        ) : (
          <div className={`${styles.bookOdds} ${styles.fairOddsDisabled}`}>
            <span className={styles.bookName}>Fair</span>
            <span className={styles.fairOddsHelp}>
              ?
              <div className={styles.fairOddsPopover}>
                <strong>
                  {formatDisabledReason(bet.ev_disabled_reason).title}
                </strong>
                <p>{formatDisabledReason(bet.ev_disabled_reason).detail}</p>
              </div>
            </span>
          </div>
        )}
        {bet.books.map((bookOdds, bookIdx) => {
          const displayEv = bookOdds.display_ev ?? bookOdds.ev_percent;
          const evColor = getEvColor(displayEv);
          return (
            <div
              key={bookIdx}
              className={`${styles.bookOdds} ${
                bestBookHasPositiveEv && bookOdds.book === bestBook.book
                  ? styles.bestOdds
                  : ""
              } ${bookOdds.is_sharp ? styles.sharpBook : ""}`}
            >
              <span className={styles.bookName}>
                {bookOdds.book}
                {bookOdds.is_sharp && (
                  <span className={styles.sharpBadge}>S</span>
                )}
              </span>
              <span className={styles.bookPrice}>
                {formatOdds(bookOdds.price)}
              </span>
              {displayEv !== null && displayEv !== undefined && (
                <span
                  className={`${styles.evBadge} ${
                    evColor === "positive"
                      ? styles.evPositive
                      : evColor === "negative"
                      ? styles.evNegative
                      : ""
                  }`}
                >
                  {formatEv(displayEv)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function FairbetLivePage() {
  const [gameLiveData, setGameLiveData] = useState<GameLiveData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedLeague, setSelectedLeague] = useState<string>("");
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [selectedSort, setSelectedSort] = useState<string>("ev");
  const [excludeAlternates, setExcludeAlternates] = useState(true);

  const [openDerivation, setOpenDerivation] = useState<string | null>(null);
  const derivationRef = useRef<HTMLDivElement | null>(null);

  // Close derivation on outside click
  useEffect(() => {
    if (openDerivation === null) return;
    function handleClickOutside(e: MouseEvent) {
      if (derivationRef.current && !derivationRef.current.contains(e.target as Node)) {
        setOpenDerivation(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [openDerivation]);

  const loadAllLiveOdds = useCallback(async () => {
    try {
      setError(null);

      // 1) Discover which games have live odds in Redis
      const liveGames = await fetchLiveGames(selectedLeague || undefined);

      if (liveGames.length === 0) {
        setGameLiveData([]);
        setLoading(false);
        return;
      }

      // 2) Fetch live odds for each game in parallel
      const results = await Promise.allSettled(
        liveGames.map(async (game) => {
          const data = await fetchFairbetLiveOdds({
            game_id: game.game_id,
            market_category: selectedCategory || undefined,
            sort_by: selectedSort,
          });
          return { game, data };
        })
      );

      const newGameData: GameLiveData[] = results.map((result, i) => {
        if (result.status === "fulfilled") {
          return {
            game: result.value.game,
            data: result.value.data,
            loading: false,
            error: null,
          };
        } else {
          return {
            game: liveGames[i],
            data: null,
            loading: false,
            error: result.reason?.message ?? "Failed to load",
          };
        }
      });

      // Filter out games with no bets
      const withBets = newGameData.filter(
        (gd) => gd.data && gd.data.bets.length > 0
      );

      setGameLiveData(withBets);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [selectedLeague, selectedCategory, selectedSort]);

  // Initial load
  useEffect(() => {
    setLoading(true);
    loadAllLiveOdds();
  }, [loadAllLiveOdds]);

  // Auto-refresh every 15 seconds
  useEffect(() => {
    const interval = setInterval(loadAllLiveOdds, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [loadAllLiveOdds]);

  // Collect all available categories across all games
  const allCategories = Array.from(
    new Set(
      gameLiveData.flatMap(
        (gd) => gd.data?.market_categories_available ?? []
      )
    )
  ).sort();

  // Count total bets across all games
  const totalBets = gameLiveData.reduce(
    (sum, gd) => sum + (gd.data?.total ?? 0),
    0
  );

  // Find most recent update across all games
  const latestUpdate = gameLiveData.reduce<string | null>((latest, gd) => {
    const ts = gd.data?.last_updated_at;
    if (!ts) return latest;
    if (!latest) return ts;
    return ts > latest ? ts : latest;
  }, null);

  // Filter bets within each game by alternate exclusion
  function getFilteredBets(data: FairbetLiveResponse): BetDefinition[] {
    let bets = data.bets;
    if (excludeAlternates) {
      bets = bets.filter((b) => b.market_category !== "alternate");
    }
    return bets;
  }

  function resetFilters() {
    setSelectedLeague("");
    setSelectedCategory("");
    setSelectedSort("ev");
    setExcludeAlternates(true);
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerRow}>
          <div>
            <h1 className={styles.title}>Live Odds</h1>
            <p className={styles.subtitle}>
              Real-time cross-book odds with +EV fair-bet analysis
            </p>
          </div>
          {gameLiveData.length > 0 && (
            <div className={styles.liveIndicator}>
              <span className={styles.liveDot} />
              <span>
                {gameLiveData.length} game{gameLiveData.length !== 1 ? "s" : ""} live
                {" · "}
                {totalBets} bet{totalBets !== 1 ? "s" : ""}
                {latestUpdate && ` · Updated ${formatLastSync(latestUpdate)}`}
              </span>
            </div>
          )}
        </div>
      </header>

      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>League</label>
          <select
            className={styles.filterSelect}
            value={selectedLeague}
            onChange={(e) => setSelectedLeague(e.target.value)}
          >
            <option value="">All Leagues</option>
            {LEAGUES.map((league) => (
              <option key={league} value={league}>{league}</option>
            ))}
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Category</label>
          <select
            className={styles.filterSelect}
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
          >
            <option value="">All Markets</option>
            {allCategories.map((cat) => (
              <option key={cat} value={cat}>{formatMarketCategory(cat)}</option>
            ))}
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={excludeAlternates}
              onChange={(e) => setExcludeAlternates(e.target.checked)}
              className={styles.checkbox}
            />
            Hide Alternates
          </label>
        </div>

        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Sort</label>
          <select
            className={styles.filterSelect}
            value={selectedSort}
            onChange={(e) => setSelectedSort(e.target.value)}
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        <div className={styles.filterGroup}>
          <button className={styles.resetButton} onClick={resetFilters}>
            Reset
          </button>
        </div>

        <div className={styles.filterGroup} style={{ marginLeft: "auto" }}>
          <span className={styles.autoRefresh}>
            <span className={styles.autoRefreshDot} />
            Auto-refreshing every 15s
          </span>
          <button
            className={styles.refreshButton}
            onClick={() => { setLoading(true); loadAllLiveOdds(); }}
            disabled={loading}
          >
            {loading ? "Refreshing..." : "Refresh Now"}
          </button>
        </div>
      </div>

      {error && <div className={styles.error}>Error: {error}</div>}

      {loading && gameLiveData.length === 0 ? (
        <div className={styles.loading}>Scanning for live games...</div>
      ) : gameLiveData.length === 0 ? (
        <div className={styles.empty}>
          No live games found.{" "}
          {selectedLeague
            ? "Try selecting a different league or wait for games to go live."
            : "Games appear here automatically when bookmakers post in-game lines."}
        </div>
      ) : (
        gameLiveData.map((gd) => {
          if (!gd.data) return null;
          const filteredBets = getFilteredBets(gd.data);
          if (filteredBets.length === 0) return null;

          return (
            <div key={gd.game.game_id} className={styles.gameSection}>
              <div className={styles.gameHeader}>
                <span className={styles.gameHeaderLeague}>
                  {gd.game.league_code}
                </span>
                <span className={styles.gameHeaderMatchup}>
                  {gd.data.away_team} @ {gd.data.home_team}
                </span>
                <span className={styles.gameHeaderStatus}>
                  <span className={styles.gameHeaderDot} />
                  {gd.game.status ?? "LIVE"}
                </span>
                {gd.data.last_updated_at && (
                  <span className={styles.gameHeaderUpdated}>
                    Updated {formatLastSync(gd.data.last_updated_at)}
                  </span>
                )}
                <span className={styles.gameHeaderCount}>
                  {filteredBets.length} bet{filteredBets.length !== 1 ? "s" : ""}
                </span>
              </div>
              <div className={styles.gameBetsGrid}>
                {filteredBets.map((bet, betIdx) => (
                  <BetCard
                    key={`${gd.game.game_id}-${betIdx}`}
                    bet={bet}
                    idx={`${gd.game.game_id}-${betIdx}`}
                    openDerivation={openDerivation}
                    setOpenDerivation={setOpenDerivation}
                    derivationRef={derivationRef}
                  />
                ))}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
