"""Admin endpoints for club provisioning.

POST /api/admin/clubs/{claim_id}/provision — operator-triggered manual provisioning.
Admin role required (enforced at router registration in main.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.provisioning import ClubProvisioningService, ProvisioningError

router = APIRouter(prefix="/clubs", tags=["admin", "provisioning"])

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)
_service = ClubProvisioningService()


class ProvisionResponse(BaseModel):
    model_config = _ALIAS_CFG

    club_id: str
    slug: str
    name: str
    plan_id: str
    status: str
    owner_user_id: int | None


@router.post(
    "/{claim_id}/provision",
    response_model=ProvisionResponse,
    status_code=status.HTTP_200_OK,
)
async def provision_club(
    claim_id: str,
    db: AsyncSession = Depends(get_db),
) -> ProvisionResponse:
    """Operator-triggered fallback for manual club provisioning.

    Idempotent: calling twice for the same claim_id returns the same club
    without creating duplicate rows.  Admin role enforced by the router
    registration in ``main.py`` (``admin_dependency``).
    """
    try:
        club = await _service.provision(db, claim_id)
    except ProvisioningError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "provisioning_failed", "message": str(exc)},
        ) from exc

    return ProvisionResponse(
        club_id=club.club_id,
        slug=club.slug,
        name=club.name,
        plan_id=club.plan_id,
        status=club.status,
        owner_user_id=club.owner_user_id,
    )
