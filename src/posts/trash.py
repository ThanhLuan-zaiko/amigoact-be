"""The post trash: listing deleted posts, restoring them, and removing them for good."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.auth import User
from src.models.organizations import Organization
from src.models.posts import OrgPost
from src.organizations.access import get_access
from src.posts.rules import (
    POST_ACTIVE,
    TRASH_DAYS,
    may_purge,
    may_restore,
    purge_at,
)
from src.posts.visibility import load_live_org


def _forbidden() -> HTTPException:
    return api_error(status.HTTP_403_FORBIDDEN, "post_forbidden")


def _not_in_trash() -> HTTPException:
    return api_error(status.HTTP_409_CONFLICT, "post_not_in_trash")


def purge_expired(db: Session, org_id: uuid.UUID, now: datetime) -> int:
    """Remove posts that stayed in the trash longer than the keep period."""
    cutoff = now - timedelta(days=TRASH_DAYS)
    result = db.execute(
        delete(OrgPost).where(
            OrgPost.org_id == org_id,
            OrgPost.deleted_at.is_not(None),
            OrgPost.deleted_at <= cutoff,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def list_trash(
    db: Session,
    org: Organization,
    user_id: uuid.UUID,
    *,
    before: uuid.UUID | None,
    limit: int,
) -> list[tuple[OrgPost, str | None]]:
    """Deleted posts of the organization, newest first. Expired ones go first."""
    if not may_restore(get_access(db, org, user_id)):
        raise _forbidden()
    purge_expired(db, org.id, datetime.now(UTC))
    db.commit()
    query = (
        select(OrgPost, User.full_name)
        .outerjoin(User, User.id == OrgPost.deleted_by)
        .where(
            OrgPost.org_id == org.id,
            OrgPost.deleted_at.is_not(None),
            OrgPost.status == POST_ACTIVE,
        )
    )
    if before is not None:
        query = query.where(OrgPost.post_id < before)
    rows = db.execute(query.order_by(OrgPost.post_id.desc()).limit(limit + 1)).all()
    return [(post, name) for post, name in rows]


def load_trashed_post(db: Session, post_id: uuid.UUID) -> tuple[OrgPost, Organization]:
    """A post and its live organization. A missing post or organization is a 404."""
    post = db.get(OrgPost, post_id)
    if post is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "post_not_found")
    return post, load_live_org(db, post.org_id)


def _check_in_trash(post: OrgPost, now: datetime) -> None:
    if post.deleted_at is None:
        raise _not_in_trash()
    if purge_at(post.deleted_at) <= now:
        # Past the keep period it is as good as gone, even before the purge runs.
        raise api_error(status.HTTP_404_NOT_FOUND, "post_not_found")


def restore_post(db: Session, post_id: uuid.UUID, user_id: uuid.UUID) -> OrgPost:
    post, org = load_trashed_post(db, post_id)
    access = get_access(db, org, user_id)
    if not may_restore(access):
        # Outsiders cannot learn that a deleted post exists.
        if access.status is None:
            raise api_error(status.HTTP_404_NOT_FOUND, "post_not_found")
        raise _forbidden()
    _check_in_trash(post, datetime.now(UTC))
    post.deleted_at = None
    post.deleted_by = None
    db.commit()
    return post


def purge_post(db: Session, post_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Remove a post from the trash for good, with its tags, media links and comments."""
    post, org = load_trashed_post(db, post_id)
    access = get_access(db, org, user_id)
    if not may_purge(access):
        if access.status is None:
            raise api_error(status.HTTP_404_NOT_FOUND, "post_not_found")
        raise _forbidden()
    _check_in_trash(post, datetime.now(UTC))
    db.delete(post)
    db.commit()
