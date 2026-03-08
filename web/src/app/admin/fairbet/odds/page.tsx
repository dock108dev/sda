"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./styles.module.css";
import {
  fetchFairbetOdds,
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
  type FairbetOddsFilters,
  type GameOption,
} from "@/lib/api/fairbet";
import { listScrapeRuns } from "@/lib/api/sportsAdmin";
import type { ScrapeRunResponse } from "@/lib/api/sportsAdmin/types";
import { FAIRBET_LEAGUES } from "@/lib/constants/sports";
import { DerivationContent } from "./DerivationContent";
import { formatGameDate, formatLastSync, formatLineValue } from "./helpers";

const LEAGUES = FAIRBET_LEAGUES;

const SORT_OPTIONS = [
  { value: "ev", label: "Best EV" },
  { value: "game_time", label: "Game Time" },
  { value: "market", label: "Market" },
];

// Shared bet card component used by both Pre-Game and Live tabs
function BetCard({
  bet,
  idx,
  openDerivation,
  setOpenDerivation,
  derivationRef,
}: {
  bet: BetDefinition;
  idx: number;
  openDerivation: number | null;
  setOpenDerivation: (idx: number | null) => void;
  derivationRef: React.RefObject<HTMLDivElement | null>;
}) {
  const bestBook = getBestOdds(bet.books);
  const bestBookEv = bestBook != null ? (bestBook.display_ev ?? bestBook.ev_percent) : null;
  const bestBookHasPositiveEv = bestBook != null && bestBookEv != null && bestBookEv > 0;

  return (
    <div className={styles.betCard}>
      <div className={styles.betHeader}>
        <div className={styles.betHeaderLeft}>
          <span className={styles.leagueBadge}>{bet.league_code}</span>
          {bet.market_category && bet.market_category !== "mainline" && (
            <span className={styles.categoryBadge}>
              {formatMarketCategory(bet.market_category)}
            </span>
          )}
        </div>
        <span className={styles.gameDate}>
          {formatGameDate(bet.game_date)}
        </span>
      </div>

      <div className={styles.matchup}>
        {bet.away_team} @ {bet.home_team}
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

// ─── Pre-Game Tab ───

function PreGameTab() {
  const [bets, setBets] = useState<BetDefinition[]>([]);
  const [booksAvailable, setBooksAvailable] = useState<string[]>([]);
  const [marketCategoriesAvailable, setMarketCategoriesAvailable] = useState<string[]>([]);
  const [gamesAvailable, setGamesAvailable] = useState<GameOption[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedLeague, setSelectedLeague] = useState<string>("");
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [selectedGame, setSelectedGame] = useState<string>("");
  const [selectedBook, setSelectedBook] = useState<string>("");
  const [selectedSort, setSelectedSort] = useState<string>("ev");
  const [excludeAlternates, setExcludeAlternates] = useState(true);
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);

  const [openDerivation, setOpenDerivation] = useState<number | null>(null);
  const derivationRef = useRef<HTMLDivElement | null>(null);

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

  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [lastOddsSync, setLastOddsSync] = useState<string | null>(null);

  const loadOdds = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const filters: FairbetOddsFilters = { limit, offset, sort_by: selectedSort };
      if (selectedLeague) filters.league = selectedLeague;
      if (selectedCategory) filters.market_category = selectedCategory;
      if (excludeAlternates) filters.exclude_categories = ["alternate"];
      if (selectedGame) filters.game_id = parseInt(selectedGame, 10);
      if (selectedBook) filters.book = selectedBook;

      const response = await fetchFairbetOdds(filters);
      setBets(response.bets);
      setBooksAvailable(response.books_available);
      setMarketCategoriesAvailable(response.market_categories_available);
      setGamesAvailable(response.games_available);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [limit, offset, selectedLeague, selectedCategory, excludeAlternates, selectedGame, selectedBook, selectedSort]);

  useEffect(() => { loadOdds(); }, [loadOdds]);

  const loadLastOddsSync = useCallback(async () => {
    try {
      const runs = await listScrapeRuns({ status: "completed" });
      const oddsRun = runs.find(
        (run: ScrapeRunResponse) => run.config?.odds === true && run.finished_at
      );
      if (oddsRun?.finished_at) setLastOddsSync(oddsRun.finished_at);
    } catch (err) {
      console.error("Failed to load last odds sync time:", err);
    }
  }, []);

  useEffect(() => { loadLastOddsSync(); }, [loadLastOddsSync]);

  async function syncOdds() {
    setSyncing(true);
    setSyncMessage(null);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (selectedLeague) params.set("league", selectedLeague);
      const res = await fetch(`/proxy/api/admin/odds/sync?${params.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(`Odds sync failed: ${res.statusText}`);
      const data = await res.json();
      const leagueLabel = selectedLeague || "all leagues";
      setSyncMessage(`Odds sync dispatched for ${leagueLabel} (task ${data.task_id}). Refreshing…`);
      setTimeout(async () => {
        await loadOdds();
        await loadLastOddsSync();
        setSyncing(false);
        setSyncMessage(null);
      }, 5000);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSyncing(false);
    }
  }

  function resetFilters() {
    setSelectedLeague("");
    setSelectedCategory("");
    setSelectedGame("");
    setSelectedBook("");
    setSelectedSort("ev");
    setExcludeAlternates(true);
    setOffset(0);
  }

  if (error) {
    return <div className={styles.error}>Error: {error}</div>;
  }

  return (
    <>
      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>League</label>
          <select className={styles.filterSelect} value={selectedLeague} onChange={(e) => { setSelectedLeague(e.target.value); setOffset(0); }}>
            <option value="">All Leagues</option>
            {LEAGUES.map((league) => <option key={league} value={league}>{league}</option>)}
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Category</label>
          <select className={styles.filterSelect} value={selectedCategory} onChange={(e) => { setSelectedCategory(e.target.value); setOffset(0); }}>
            <option value="">All Markets</option>
            {marketCategoriesAvailable.map((cat) => <option key={cat} value={cat}>{formatMarketCategory(cat)}</option>)}
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label className={styles.checkboxLabel}>
            <input type="checkbox" checked={excludeAlternates} onChange={(e) => { setExcludeAlternates(e.target.checked); setOffset(0); }} className={styles.checkbox} />
            Hide Alternates
          </label>
        </div>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Game</label>
          <select className={styles.filterSelect} value={selectedGame} onChange={(e) => { setSelectedGame(e.target.value); setOffset(0); }}>
            <option value="">All Games</option>
            {gamesAvailable.map((g) => <option key={g.game_id} value={g.game_id.toString()}>{g.matchup}</option>)}
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Book</label>
          <select className={styles.filterSelect} value={selectedBook} onChange={(e) => { setSelectedBook(e.target.value); setOffset(0); }}>
            <option value="">All Books</option>
            {booksAvailable.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Sort</label>
          <select className={styles.filterSelect} value={selectedSort} onChange={(e) => { setSelectedSort(e.target.value); setOffset(0); }}>
            {SORT_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
          </select>
        </div>
        <div className={styles.filterGroup}>
          <button className={styles.resetButton} onClick={resetFilters}>Reset</button>
        </div>
        <div className={styles.filterGroup} style={{ marginLeft: "auto", textAlign: "right" }}>
          {lastOddsSync && <span className={styles.lastSync}>Last sync: {formatLastSync(lastOddsSync)}</span>}
          <button
            className={`${styles.syncButton} ${syncing ? styles.syncButtonActive : ""}`}
            onClick={syncOdds}
            disabled={syncing}
          >
            {syncing ? (syncMessage ? "Refreshing…" : "Syncing…") : selectedLeague ? `Sync ${selectedLeague} Odds` : "Sync All Odds"}
          </button>
        </div>
      </div>

      {syncMessage && <div className={styles.syncMessage}>{syncMessage}</div>}

      {loading ? (
        <div className={styles.loading}>Loading odds...</div>
      ) : bets.length === 0 ? (
        <div className={styles.empty}>No upcoming bets found.{selectedLeague && " Try selecting a different league."}</div>
      ) : (
        <>
          <div className={styles.betsGrid}>
            {bets.map((bet, idx) => (
              <BetCard
                key={idx}
                bet={bet}
                idx={idx}
                openDerivation={openDerivation}
                setOpenDerivation={setOpenDerivation}
                derivationRef={derivationRef}
              />
            ))}
          </div>
          <div className={styles.pagination}>
            <button className={styles.pageButton} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
            <span className={styles.pageInfo}>Showing {offset + 1}-{Math.min(offset + limit, total)} of {total}</span>
            <button className={styles.pageButton} disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button>
          </div>
        </>
      )}
    </>
  );
}

// ─── Main Page ───

export default function FairbetOddsPage() {
  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>FairBet Odds</h1>
        <p className={styles.subtitle}>
          Cross-book odds comparison with +EV fair-bet analysis (Pre-Game)
        </p>
      </header>

      <PreGameTab />
    </div>
  );
}
