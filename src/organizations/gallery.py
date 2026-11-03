"""The gallery of an organization: up to ten pictures and videos."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.deps import CurrentPrincipal, Db
from src.auth.errors import api_error
from src.media import service as media_service
from src.models.media import MediaAsset
from src.models.organizations import Organization, OrganizationMedia
from src.organizations.access import require_manager
from src.organizations.pictures import picture_url
from src.organizations.service import load_organization
from src.validation import Uuid7

MAX_GALLERY_ITEMS = 10
Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]

router = APIRouter(prefix="/organizations", tags=["organizations"])


class GalleryAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: Uuid7


class GalleryItem(BaseModel):
    id: uuid.UUID
    url: str
    mime: str


def has_room(count: int) -> bool:
    return count < MAX_GALLERY_ITEMS


def list_items(db: Session, org_id: uuid.UUID) -> list[GalleryItem]:
    rows = db.scalars(
        select(MediaAsset)
        .join(OrganizationMedia, OrganizationMedia.asset_id == MediaAsset.asset_id)
        .where(OrganizationMedia.org_id == org_id)
        .order_by(OrganizationMedia.created_at, OrganizationMedia.asset_id)
    ).all()
    return [
        GalleryItem(
            id=asset.asset_id,
            url=picture_url(asset.asset_id) or "",
            mime=asset.mime or "application/octet-stream",
        )
        for asset in rows
    ]


def add_item(
    db: Session, org: Organization, asset_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Lock the organization first, so parallel uploads cannot pass the limit together."""
    db.execute(
        select(Organization.id).where(Organization.id == org.id).with_for_update()
    )
    # The same file added twice is one item, so a retried upload changes nothing.
    if db.get(OrganizationMedia, (org.id, asset_id)) is not None:
        return
    count = db.scalar(
        select(func.count())
        .select_from(OrganizationMedia)
        .where(OrganizationMedia.org_id == org.id)
    )
    if not has_room(count or 0):
        raise api_error(status.HTTP_409_CONFLICT, "gallery_full")
    media_service.check_attachable(db, asset_id, user_id, allow_video=True)
    db.add(OrganizationMedia(org_id=org.id, asset_id=asset_id, added_by=user_id))
    db.commit()


@router.get("/{slug}/gallery")
def get_gallery(slug: Slug, db: Db) -> list[GalleryItem]:
    return list_items(db, load_organization(db, slug).id)


@router.post("/{slug}/gallery", status_code=status.HTTP_201_CREATED)
def add_to_gallery(
    slug: Slug, payload: GalleryAddRequest, principal: CurrentPrincipal, db: Db
) -> list[GalleryItem]:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    add_item(db, org, payload.asset_id, principal.user.id)
    return list_items(db, org.id)


@router.delete("/{slug}/gallery/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_gallery(
    slug: Slug, asset_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    item = db.get(OrganizationMedia, (org.id, asset_id))
    if item is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "media_not_found")
    db.delete(item)
    db.commit()
