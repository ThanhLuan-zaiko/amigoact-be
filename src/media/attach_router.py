"""Routes that set or clear a picture: a user's avatar, an org's logo or cover, an activity's cover."""

import uuid
from typing import Annotated

from fastapi import APIRouter, status
from fastapi import Path as PathParam
from sqlalchemy.orm import Session

from src.activities import service as activity_service
from src.auth.deps import CurrentPrincipal, Db
from src.media import service
from src.media.schemas import AttachRequest
from src.organizations.access import require_manager
from src.organizations.service import load_organization
from src.validation import Uuid7

router = APIRouter(tags=["media"])

Slug = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9-]{1,80}$")]


@router.put("/account/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
def set_avatar(payload: AttachRequest, principal: CurrentPrincipal, db: Db) -> None:
    principal.user.avatar_media_id = _attach(db, payload, principal.user.id)
    db.commit()


@router.put("/organizations/{slug}/logo", status_code=status.HTTP_204_NO_CONTENT)
def set_logo(
    slug: Slug,
    payload: AttachRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    org.logo_media_id = _attach(db, payload, principal.user.id)
    db.commit()


@router.put("/organizations/{slug}/cover", status_code=status.HTTP_204_NO_CONTENT)
def set_org_cover(
    slug: Slug,
    payload: AttachRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    org.cover_media_id = _attach(db, payload, principal.user.id)
    db.commit()


@router.put("/activities/{activity_id}/cover", status_code=status.HTTP_204_NO_CONTENT)
def set_activity_cover(
    activity_id: Uuid7,
    payload: AttachRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    activity = activity_service.load_activity(db, activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    activity.cover_media_id = _attach(db, payload, principal.user.id)
    db.commit()


def _attach(
    db: Session, payload: AttachRequest, user_id: uuid.UUID
) -> uuid.UUID | None:
    if payload.asset_id is None:
        return None
    return service.check_attachable(db, payload.asset_id, user_id).asset_id
