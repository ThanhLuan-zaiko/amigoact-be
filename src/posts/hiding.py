"""Hiding a published post from the feed without deleting it.

A hidden post is gone for everyone except the organization's managers, who
still see it in the organization feed, marked hidden, so they can bring it back.
"""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.organizations import Organization
from src.models.posts import OrgPost
from src.organizations.access import ACTIVE, Access, get_access
from src.posts.rules import POST_ACTIVE


def sees_hidden(access: Access | None) -> bool:
    """Only an active owner or admin sees hidden posts."""
    return access is not None and access.status == ACTIVE and access.can_manage


def viewer_sees_hidden(
    db: Session, org: Organization, viewer_id: uuid.UUID | None
) -> bool:
    if viewer_id is None:
        return False
    return sees_hidden(get_access(db, org, viewer_id))


def set_hidden(
    db: Session, post: OrgPost, org: Organization, user_id: uuid.UUID, hidden: bool
) -> None:
    """Hiding also unpins, so a hidden post never sits at the top of the feed."""
    if not viewer_sees_hidden(db, org, user_id):
        raise api_error(status.HTTP_403_FORBIDDEN, "post_forbidden")
    if post.status != POST_ACTIVE:
        raise api_error(status.HTTP_409_CONFLICT, "post_not_published")
    if hidden:
        post.hidden_at = post.hidden_at or datetime.now(UTC)
        post.hidden_by = post.hidden_by or user_id
        post.pinned_at = None
    else:
        post.hidden_at = None
        post.hidden_by = None
    db.commit()
