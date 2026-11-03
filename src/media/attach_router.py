"""Routes that set or clear a picture: a user's avatar, an org's logo or cover, an activity's cover."""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi import Path as PathParam
from sqlalchemy.orm import Session

from src.activities import service as activity_service
from src.auth.deps import CurrentPrincipal, Db
from src.media import placement, service
from src.media.schemas import AttachRequest
from src.media.storage import get_media_root
from src.organizations.access import require_manager
from src.organizations.service import load_organization
from src.validation import Uuid7

router = APIRouter(tags=["media"])

Slug = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9-]{1,80}$")]
MediaRoot = Annotated[Path, Depends(get_media_root)]


@router.put("/account/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
def set_avatar(
    payload: AttachRequest, principal: CurrentPrincipal, db: Db, root: MediaRoot
) -> None:
    previous = principal.user.avatar_media_id
    current = _attach(db, payload, principal.user.id)
    principal.user.avatar_media_id = current
    db.commit()
    placement.replace(db, root, previous, current, "avatar")


@router.put("/organizations/{slug}/logo", status_code=status.HTTP_204_NO_CONTENT)
def set_logo(
    slug: Slug,
    payload: AttachRequest,
    principal: CurrentPrincipal,
    db: Db,
    root: MediaRoot,
) -> None:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    previous = org.logo_media_id
    current = _attach(db, payload, principal.user.id)
    org.logo_media_id = current
    db.commit()
    placement.replace(db, root, previous, current, "organizations", str(org.id), "logo")


@router.put("/organizations/{slug}/cover", status_code=status.HTTP_204_NO_CONTENT)
def set_org_cover(
    slug: Slug,
    payload: AttachRequest,
    principal: CurrentPrincipal,
    db: Db,
    root: MediaRoot,
) -> None:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    previous = org.cover_media_id
    current = _attach(db, payload, principal.user.id)
    org.cover_media_id = current
    db.commit()
    placement.replace(
        db, root, previous, current, "organizations", str(org.id), "cover"
    )


@router.put("/activities/{activity_id}/cover", status_code=status.HTTP_204_NO_CONTENT)
def set_activity_cover(
    activity_id: Uuid7,
    payload: AttachRequest,
    principal: CurrentPrincipal,
    db: Db,
    root: MediaRoot,
) -> None:
    activity = activity_service.load_activity(db, activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    previous = activity.cover_media_id
    current = _attach(db, payload, principal.user.id)
    activity.cover_media_id = current
    db.commit()
    placement.replace(
        db, root, previous, current, "activities", str(activity.id), "cover"
    )


def _attach(
    db: Session, payload: AttachRequest, user_id: uuid.UUID
) -> uuid.UUID | None:
    if payload.asset_id is None:
        return None
    return service.check_attachable(db, payload.asset_id, user_id).asset_id
