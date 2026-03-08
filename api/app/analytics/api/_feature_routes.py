"""Feature loadout CRUD endpoints (DB-backed)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.analytics import AnalyticsFeatureConfig

router = APIRouter()


class FeatureLoadoutCreateRequest(BaseModel):
    """Request body for POST /api/analytics/feature-config."""
    name: str = Field(..., description="Loadout name")
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    model_type: str = Field(..., description="Model type (e.g., plate_appearance, game)")
    features: list[dict[str, Any]] = Field(
        ..., description="Array of {name, enabled, weight} dicts",
    )
    is_default: bool = Field(False, description="Whether this is the default loadout")


class FeatureLoadoutUpdateRequest(BaseModel):
    """Request body for PUT /api/analytics/feature-config/{id}."""
    name: str | None = Field(None, description="New loadout name")
    sport: str | None = Field(None, description="Sport code")
    model_type: str | None = Field(None, description="Model type")
    features: list[dict[str, Any]] | None = Field(
        None, description="Array of {name, enabled, weight} dicts",
    )
    is_default: bool | None = Field(None, description="Default flag")


def _serialize_loadout(row: AnalyticsFeatureConfig) -> dict[str, Any]:
    """Serialize a DB feature config row to API response dict."""
    features = row.features or []
    enabled = [f["name"] for f in features if f.get("enabled", True)]
    return {
        "id": row.id,
        "name": row.name,
        "sport": row.sport,
        "model_type": row.model_type,
        "features": features,
        "is_default": row.is_default,
        "enabled_count": len(enabled),
        "total_count": len(features),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/feature-configs")
async def list_feature_configs(
    sport: str = Query(None, description="Filter by sport"),
    model_type: str = Query(None, description="Filter by model type"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all saved feature loadouts."""
    stmt = select(AnalyticsFeatureConfig).order_by(
        AnalyticsFeatureConfig.updated_at.desc()
    )
    if sport:
        stmt = stmt.where(AnalyticsFeatureConfig.sport == sport)
    if model_type:
        stmt = stmt.where(AnalyticsFeatureConfig.model_type == model_type)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    loadouts = [_serialize_loadout(r) for r in rows]

    return {
        "loadouts": loadouts,
        "count": len(loadouts),
    }


@router.get("/feature-config/{config_id}")
async def get_feature_config_by_id(
    config_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a feature loadout by ID."""
    row = await db.get(AnalyticsFeatureConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feature config not found")
    return _serialize_loadout(row)


@router.post("/feature-config")
async def create_feature_config(
    req: FeatureLoadoutCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new feature loadout."""
    row = AnalyticsFeatureConfig(
        name=req.name,
        sport=req.sport.lower(),
        model_type=req.model_type,
        features=req.features,
        is_default=req.is_default,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return {"status": "created", **_serialize_loadout(row)}


@router.put("/feature-config/{config_id}")
async def update_feature_config(
    config_id: int,
    req: FeatureLoadoutUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update an existing feature loadout."""
    row = await db.get(AnalyticsFeatureConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feature config not found")

    if req.name is not None:
        row.name = req.name
    if req.sport is not None:
        row.sport = req.sport.lower()
    if req.model_type is not None:
        row.model_type = req.model_type
    if req.features is not None:
        row.features = req.features
    if req.is_default is not None:
        row.is_default = req.is_default

    await db.flush()
    await db.refresh(row)
    return {"status": "updated", **_serialize_loadout(row)}


@router.delete("/feature-config/{config_id}")
async def delete_feature_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a feature loadout."""
    row = await db.get(AnalyticsFeatureConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feature config not found")
    name = row.name
    await db.delete(row)
    return {"status": "deleted", "id": config_id, "name": name}


@router.post("/feature-config/{config_id}/clone")
async def clone_feature_config(
    config_id: int,
    name: str = Query(None, description="Name for the cloned loadout"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Clone an existing feature loadout."""
    row = await db.get(AnalyticsFeatureConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feature config not found")

    clone_name = name or f"{row.name} (copy)"
    clone = AnalyticsFeatureConfig(
        name=clone_name,
        sport=row.sport,
        model_type=row.model_type,
        features=list(row.features),
        is_default=False,
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)
    return {"status": "cloned", **_serialize_loadout(clone)}


@router.get("/available-features")
async def get_available_features(
    sport: str = Query("mlb", description="Sport code"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List available features with descriptions and DB coverage stats."""
    if sport.lower() == "mlb":
        return await _get_mlb_available_features(db)
    return {"sport": sport, "features": [], "message": "Sport not supported yet"}


async def _get_mlb_available_features(db: AsyncSession) -> dict[str, Any]:
    """Get available MLB features from the MLBFeatureBuilder and DB stats."""
    from app.analytics.features.sports.mlb_features import _PA_FEATURES, _GAME_FEATURES
    from app.db.mlb_advanced import MLBGameAdvancedStats

    from sqlalchemy import func as sa_func
    count_result = await db.execute(
        select(sa_func.count(MLBGameAdvancedStats.id))
    )
    total_games = count_result.scalar() or 0

    pa_features = []
    for feat_name, entity, source_key in _PA_FEATURES:
        pa_features.append({
            "name": feat_name,
            "entity": entity,
            "source_key": source_key,
            "description": _feature_description(feat_name, source_key),
            "data_type": "float",
            "model_types": ["plate_appearance"],
        })

    game_features = []
    for feat_name, entity, source_key in _GAME_FEATURES:
        game_features.append({
            "name": feat_name,
            "entity": entity,
            "source_key": source_key,
            "description": _feature_description(feat_name, source_key),
            "data_type": "float",
            "model_types": ["game"],
        })

    return {
        "sport": "mlb",
        "total_games_with_data": total_games,
        "plate_appearance_features": pa_features,
        "game_features": game_features,
        "all_features": pa_features + game_features,
    }


def _feature_description(feat_name: str, source_key: str) -> str:
    """Generate a human-readable description for a feature."""
    descriptions: dict[str, str] = {
        "contact_rate": "Rate of contact made on swings",
        "power_index": "Composite power metric based on exit velocity and barrel rate",
        "barrel_rate": "Percentage of batted balls classified as barrels",
        "hard_hit_rate": "Percentage of batted balls with exit velocity >= 95 mph",
        "swing_rate": "Percentage of pitches swung at",
        "whiff_rate": "Percentage of swings that miss (swinging strikes / swings)",
        "avg_exit_velocity": "Average exit velocity on batted balls (mph)",
        "expected_slug": "Expected slugging percentage based on quality of contact",
    }
    prefix = feat_name.split("_")[0]
    entity_label = {
        "batter": "Batter's", "pitcher": "Pitcher's",
        "home": "Home team's", "away": "Away team's",
    }.get(prefix, "")
    base_desc = descriptions.get(source_key, source_key.replace("_", " "))
    return f"{entity_label} {base_desc}".strip()
