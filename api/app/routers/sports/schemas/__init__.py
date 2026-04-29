"""Pydantic schemas for sports admin endpoints.

Re-exports all models from domain-grouped sub-modules so callers can
import directly from the schemas package.
"""

from .common import (
    GamePhase,
    LiveSnapshot,
    MediaType,
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
    ConsumerGameFlowResponse,
    FlowStatusResponse,
    GameFlowBlock,
    GameFlowContent,
    GameFlowMoment,
    GameFlowPlay,
    GameFlowResponse,
    MomentBoxScore,
    MomentGoalieStat,
    MomentPlayerStat,
    MomentTeamBoxScore,
    ScoreObject,
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
from .nba_advanced import NBAAdvancedPlayerStats, NBAAdvancedTeamStats
from .ncaab_advanced import NCAABAdvancedPlayerStats, NCAABAdvancedTeamStats
from .nfl_advanced import NFLAdvancedPlayerStats, NFLAdvancedTeamStats
from .nhl_advanced import NHLAdvancedTeamStats, NHLGoalieAdvancedStats, NHLSkaterAdvancedStats
from .scraper import ScrapeRunConfig, ScrapeRunCreateRequest, ScrapeRunResponse
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
    "MediaType",
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
    "ConsumerGameFlowResponse",
    "FlowStatusResponse",
    "GameFlowBlock",
    "GameFlowContent",
    "GameFlowMoment",
    "GameFlowPlay",
    "GameFlowResponse",
    "MomentBoxScore",
    "MomentGoalieStat",
    "MomentPlayerStat",
    "MomentTeamBoxScore",
    "ScoreObject",
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
    # ncaab_advanced
    "NCAABAdvancedPlayerStats",
    "NCAABAdvancedTeamStats",
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
