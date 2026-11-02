"""Who may see a post. The same rules feed every list and every single read."""

import uuid

from fastapi import status
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from src.auth.errors import api_error
from src.models.organizations import Organization, OrganizationMember
from src.models.posts import OrgPost
from src.organizations.access import ACTIVE, get_access
from src.organizations.service import live_organization
from src.posts.rules import MEMBERS, POST_ACTIVE, POST_DRAFT, PUBLIC


def member_org_ids(user_id: uuid.UUID) -> Select:
    return select(OrganizationMember.org_id).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.status == ACTIVE,
    )


def visible_to(viewer_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Public posts are for everyone. Member posts are for active members of that org."""
    public = OrgPost.visibility == PUBLIC
    if viewer_id is None:
        return public
    return or_(public, OrgPost.org_id.in_(member_org_ids(viewer_id)))


def published_posts(viewer_id: uuid.UUID | None) -> Select:
    """Live, published, not deleted, in a live organization, and visible to the viewer."""
    return (
        select(OrgPost)
        .join(Organization, Organization.id == OrgPost.org_id)
        .where(
            OrgPost.status == POST_ACTIVE,
            OrgPost.deleted_at.is_(None),
            *live_organization(),
            visible_to(viewer_id),
        )
    )


def load_live_org(db: Session, org_id: uuid.UUID) -> Organization:
    org = db.scalar(
        select(Organization).where(Organization.id == org_id, *live_organization())
    )
    if org is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "post_not_found")
    return org


def load_visible_post(
    db: Session, post_id: uuid.UUID, viewer_id: uuid.UUID | None
) -> OrgPost:
    """Anything the viewer may not see looks like it does not exist."""
    post = db.get(OrgPost, post_id)
    if post is None or post.deleted_at is not None:
        raise api_error(status.HTTP_404_NOT_FOUND, "post_not_found")
    org = load_live_org(db, post.org_id)
    if post.status == POST_DRAFT:
        if viewer_id is None or post.author_id != viewer_id:
            raise api_error(status.HTTP_404_NOT_FOUND, "post_not_found")
        return post
    if post.visibility == MEMBERS and (
        viewer_id is None or get_access(db, org, viewer_id).status != ACTIVE
    ):
        raise api_error(status.HTTP_404_NOT_FOUND, "post_not_found")
    return post
