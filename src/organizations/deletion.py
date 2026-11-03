"""Soft delete, trash, and restore of an organization.

A soft delete keeps every row and file. It hides the organization at once and frees its
slug. The owner finds it in the trash and can restore it, as long as the old slug is
still free and the owner is below the limit of owned organizations.
"""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.media import service as media_service
from src.media.usage import reference_count
from src.models.media import MediaAsset
from src.models.organizations import Organization, OrganizationMedia
from src.organizations.open_activities import open_activity_count
from src.organizations.schemas import DeletedOrganization
from src.organizations.service import enforce_owned_limit, live_organization

DELETED_SLUG_PREFIX = "deleted-"


def released_slug() -> str:
    """A slug nobody can type, so the public name is free for a new organization."""
    return f"{DELETED_SLUG_PREFIX}{uuid.uuid7().hex}"


def mark_deleted(org: Organization, now: datetime) -> None:
    """Hide the organization and release its slug. Nothing else changes.

    The old slug moves to previous_slug, so a restore can take it back.
    """
    org.previous_slug = org.slug
    org.slug = released_slug()
    org.deleted_at = now


def own_reference_count(
    asset_id: uuid.UUID,
    logo_id: uuid.UUID | None,
    cover_id: uuid.UUID | None,
    gallery_ids: set[uuid.UUID],
) -> int:
    """How many references the organization itself holds to this asset."""
    return (
        int(asset_id == logo_id)
        + int(asset_id == cover_id)
        + int(asset_id in gallery_ids)
    )


def picture_ids(org: Organization, gallery_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Every file the organization shows: its logo, its cover, and its gallery."""
    pictures = set(gallery_ids)
    pictures.update(
        asset for asset in (org.logo_media_id, org.cover_media_id) if asset is not None
    )
    return pictures


def gallery_ids(db: Session, org_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(OrganizationMedia.asset_id).where(OrganizationMedia.org_id == org_id)
        )
    )


def lock_live_organization(db: Session, org_id: uuid.UUID) -> bool:
    """Lock the organization row, and report whether it is still live.

    Publishing an activity and soft-deleting the organization both take this lock, so
    the two cannot interleave: whichever runs second sees the first one's commit.
    """
    locked = db.scalar(
        select(Organization.id)
        .where(Organization.id == org_id, *live_organization())
        .with_for_update()
    )
    return locked is not None


def hide_unshared_pictures(db: Session, org: Organization) -> None:
    """Make a picture private, unless another row still uses the same file.

    Each file is locked before its references are counted. Attaching locks the same row,
    so no new reference can appear between the count and the change. Files are locked in
    id order, the order the cleanup uses, so the two cannot deadlock.
    """
    gallery = gallery_ids(db, org.id)
    for asset_id in sorted(picture_ids(org, gallery)):
        asset = db.get(MediaAsset, asset_id, with_for_update=True)
        if asset is None:
            continue
        own = own_reference_count(
            asset_id, org.logo_media_id, org.cover_media_id, gallery
        )
        if reference_count(db, asset_id) == own:
            asset.visibility = media_service.PRIVATE


def show_pictures(db: Session, org: Organization) -> None:
    gallery = gallery_ids(db, org.id)
    for asset_id in picture_ids(org, gallery):
        asset = db.get(MediaAsset, asset_id)
        if asset is not None:
            media_service.publish_asset(asset)


def has_open_activities(db: Session, org_id: uuid.UUID) -> bool:
    return open_activity_count(db, org_id) > 0


def soft_delete_organization(db: Session, org: Organization) -> None:
    # Lock the row first. Publishing an activity takes the same lock, so an activity
    # cannot open between the check below and the commit.
    db.get(Organization, org.id, with_for_update=True)
    if has_open_activities(db, org.id):
        raise api_error(status.HTTP_409_CONFLICT, "organization_has_open_activities")
    hide_unshared_pictures(db, org)
    mark_deleted(org, datetime.now(UTC))
    db.commit()


def list_deleted_organizations(
    db: Session, owner_id: uuid.UUID
) -> list[DeletedOrganization]:
    rows = db.scalars(
        select(Organization)
        .where(Organization.owner_id == owner_id, Organization.deleted_at.is_not(None))
        .order_by(Organization.deleted_at.desc(), Organization.id)
    ).all()
    return [
        DeletedOrganization(
            id=org.id,
            name=org.name,
            slug=org.previous_slug,
            deleted_at=org.deleted_at,
        )
        for org in rows
    ]


def restore_organization(
    db: Session, owner_id: uuid.UUID, org_id: uuid.UUID
) -> Organization:
    """Bring a deleted organization back. Only its owner sees it in the trash."""
    org = db.scalar(
        select(Organization)
        .where(
            Organization.id == org_id,
            Organization.owner_id == owner_id,
            Organization.deleted_at.is_not(None),
        )
        .with_for_update()
    )
    if org is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "organization_not_found")
    # The organization is still deleted here, so it does not count against the limit yet.
    enforce_owned_limit(db, owner_id)
    slug = org.previous_slug
    if slug is None or db.scalar(select(exists().where(Organization.slug == slug))):
        raise api_error(status.HTTP_409_CONFLICT, "slug_taken")
    org.slug = slug
    org.previous_slug = None
    org.deleted_at = None
    show_pictures(db, org)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise api_error(status.HTTP_409_CONFLICT, "slug_taken") from exc
    return org
