"""Choosing the logo and cover in one step.

A manager can make any picture the organization already shows (its logo, its
cover, or a gallery picture) the logo or the cover, even when another manager
uploaded it. A new upload still follows the uploader rule. Both roles change in
one transaction, so swapping the logo and the cover is a single request.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.deps import CurrentPrincipal, Db
from src.auth.errors import api_error
from src.media import service as media_service
from src.models.media import MediaAsset
from src.models.organizations import Organization, OrganizationMedia
from src.organizations.access import require_permission
from src.organizations.gallery_items import MAX_GALLERY_ITEMS
from src.organizations.permissions import ORGANIZATION_UPDATE
from src.organizations.schemas import StrictRequest
from src.organizations.service import load_organization
from src.validation import Uuid7

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]

router = APIRouter(prefix="/organizations", tags=["organizations"])


class PictureChoice(StrictRequest):
    """A field left out stays as it is. Null clears that picture."""

    logo_asset_id: Uuid7 | None = None
    cover_asset_id: Uuid7 | None = None


def owned_picture_ids(org: Organization, gallery_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Pictures the organization already shows, which any manager may reuse."""
    current = {org.logo_media_id, org.cover_media_id}
    return {asset_id for asset_id in current if asset_id is not None} | gallery_ids


def _gallery_ids(db: Session, org: Organization) -> set[uuid.UUID]:
    rows = db.scalars(
        select(OrganizationMedia.asset_id).where(OrganizationMedia.org_id == org.id)
    )
    return set(rows)


def _resolve(
    db: Session, asset_id: uuid.UUID | None, owned: set[uuid.UUID], user_id: uuid.UUID
) -> uuid.UUID | None:
    if asset_id is None:
        return None
    if asset_id not in owned:
        return media_service.check_attachable(db, asset_id, user_id).asset_id
    asset = db.get(MediaAsset, asset_id, with_for_update=True)
    if asset is None or asset.upload_status != media_service.ACTIVE:
        raise api_error(status.HTTP_404_NOT_FOUND, "media_not_found")
    # A gallery video can never be a logo or a cover.
    media_service.reject_video(asset)
    asset.visibility = media_service.PUBLIC
    return asset.asset_id


@router.put("/{slug}/pictures", status_code=status.HTTP_204_NO_CONTENT)
def choose_pictures(
    slug: Slug, payload: PictureChoice, principal: CurrentPrincipal, db: Db
) -> None:
    org = load_organization(db, slug)
    require_permission(db, org, principal.user.id, ORGANIZATION_UPDATE)
    # Locked like a gallery add, so parallel requests cannot pass the gallery limit.
    db.execute(
        select(Organization.id).where(Organization.id == org.id).with_for_update()
    )
    gallery = _gallery_ids(db, org)
    owned = owned_picture_ids(org, gallery)
    before = (org.logo_media_id, org.cover_media_id)
    fields = payload.model_fields_set
    logo = _resolve(db, payload.logo_asset_id, owned, principal.user.id)
    cover = _resolve(db, payload.cover_asset_id, owned, principal.user.id)
    if "logo_asset_id" in fields:
        org.logo_media_id = logo
    if "cover_asset_id" in fields:
        org.cover_media_id = cover
    after = (org.logo_media_id, org.cover_media_id)
    room = MAX_GALLERY_ITEMS - len(gallery)
    for asset_id in keep_in_gallery(before, after, gallery)[: max(room, 0)]:
        db.add(
            OrganizationMedia(
                org_id=org.id, asset_id=asset_id, added_by=principal.user.id
            )
        )
    db.commit()


def keep_in_gallery(
    before: tuple[uuid.UUID | None, uuid.UUID | None],
    after: tuple[uuid.UUID | None, uuid.UUID | None],
    gallery: set[uuid.UUID],
) -> list[uuid.UUID]:
    """A replaced logo or cover moves to the gallery, so one click brings it back."""
    kept = []
    for asset_id in before:
        if asset_id is None or asset_id in after or asset_id in gallery:
            continue
        if asset_id not in kept:
            kept.append(asset_id)
    return kept
