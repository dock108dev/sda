export type TeamSummary = {
  id: number;
  name: string;
  shortName: string;
  abbreviation: string;
  leagueCode: string;
  gamesCount: number;
  colorLightHex: string | null;
  colorDarkHex: string | null;
};

export type TeamListResponse = {
  teams: TeamSummary[];
  total: number;
};

export type TeamGameSummary = {
  id: number;
  gameDate: string;
  opponent: string;
  isHome: boolean;
  score: string;
  result: string;
};

export type TeamDetail = {
  id: number;
  name: string;
  shortName: string;
  abbreviation: string;
  leagueCode: string;
  location: string | null;
  externalRef: string | null;
  colorLightHex: string | null;
  colorDarkHex: string | null;
  recentGames: TeamGameSummary[];
};
