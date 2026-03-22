"""Pydantic schemas for sports admin endpoints.

Re-exports all models from domain-grouped sub-modules so callers can
import directly from the schemas package.
"""

from .common import (
    GamePhase,
    LiveSnapshot,
    MLBBatterStat,
    MLBPitcherStat,
    NHLDataHealth,
    NHLGoalieStat,
    NHLSkaterStat,
    NormalizedStat,
    OddsEntry,
    PlayEntry,
    PlayerStat,
    SocialPostEntry,
    TeamStat,
    TieredPlayGroup,
)
from .diagnostics import GameConflictEntry, JobRunResponse, MissingPbpEntry
from .game_flow import (
    BlockMiniBox,
    GameFlowBlock,
    GameFlowContent,
    GameFlowMoment,
    GameFlowPlay,
    GameFlowResponse,
    MomentBoxScore,
    MomentGoalieStat,
    MomentPlayerStat,
    MomentTeamBoxScore,
    TimelineArtifactResponse,
)
from .games import (
    GameDetailResponse,
    GameListResponse,
    GameMeta,
    GamePreviewScoreResponse,
    GameSummary,
    JobResponse,
)
from .mlb_advanced import (
    MLBAdvancedPlayerStats,
    MLBAdvancedTeamStats,
    MLBFieldingStatSchema,
    MLBPitcherGameStatSchema,
)
from .scraper import ScrapeRunConfig, ScrapeRunCreateRequest, ScrapeRunResponse
from .nba_advanced import NBAAdvancedPlayerStats, NBAAdvancedTeamStats
from .nfl_advanced import NFLAdvancedPlayerStats, NFLAdvancedTeamStats
from .nhl_advanced import NHLAdvancedTeamStats, NHLGoalieAdvancedStats, NHLSkaterAdvancedStats
from .season_audit import SeasonAuditResponse
from .teams import (
    TeamColorUpdate,
    TeamDetail,
    TeamGameSummary,
    TeamListResponse,
    TeamSocialInfo,
    TeamSummary,
)

__all__ = [
    # common
    "GamePhase",
    "LiveSnapshot",
    "MLBBatterStat",
    "MLBPitcherStat",
    "NHLDataHealth",
    "NHLGoalieStat",
    "NHLSkaterStat",
    "NormalizedStat",
    "OddsEntry",
    "PlayEntry",
    "PlayerStat",
    "SocialPostEntry",
    "TeamStat",
    "TieredPlayGroup",
    # diagnostics
    "GameConflictEntry",
    "JobRunResponse",
    "MissingPbpEntry",
    # game_flow
    "BlockMiniBox",
    "GameFlowBlock",
    "GameFlowContent",
    "GameFlowMoment",
    "GameFlowPlay",
    "GameFlowResponse",
    "MomentBoxScore",
    "MomentGoalieStat",
    "MomentPlayerStat",
    "MomentTeamBoxScore",
    "TimelineArtifactResponse",
    # games
    "GameDetailResponse",
    "GameListResponse",
    "GameMeta",
    "GamePreviewScoreResponse",
    "GameSummary",
    "JobResponse",
    # mlb_advanced
    "MLBAdvancedPlayerStats",
    "MLBAdvancedTeamStats",
    "MLBFieldingStatSchema",
    "MLBPitcherGameStatSchema",
    # scraper
    "ScrapeRunConfig",
    "ScrapeRunCreateRequest",
    "ScrapeRunResponse",
    # teams
    "TeamColorUpdate",
    "TeamDetail",
    "TeamGameSummary",
    "TeamListResponse",
    "TeamSocialInfo",
    "TeamSummary",
    # nba_advanced
    "NBAAdvancedPlayerStats",
    "NBAAdvancedTeamStats",
    # nfl_advanced
    "NFLAdvancedPlayerStats",
    "NFLAdvancedTeamStats",
    # nhl_advanced
    "NHLAdvancedTeamStats",
    "NHLGoalieAdvancedStats",
    "NHLSkaterAdvancedStats",
    # season_audit
    "SeasonAuditResponse",
]
