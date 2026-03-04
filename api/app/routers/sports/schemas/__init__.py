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
from .mlb_advanced import MLBAdvancedTeamStats
from .scraper import ScrapeRunConfig, ScrapeRunCreateRequest, ScrapeRunResponse
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
    "MLBAdvancedTeamStats",
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
]
