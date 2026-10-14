"""Guest-facing announcement reads. No auth required.

Path uses /announcements/ instead of /posts/ on purpose: /orgs/{id}/posts/*
is the member-only board surface, and a same-shaped public route would
shadow it for whichever router registers first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from core.dependencies_workspace import get_public_post_service
from orgs.schemas import PublicOrgPostItem
from posts.helpers import parse_cursor
from posts.mappers import to_post
from posts.schemas import (
    PostResponse,
    PublicAnnouncementPage,
    PublicTimelineItem,
    PublicTimelineOrg,
    PublicTimelinePage,
)

if TYPE_CHECKING:
    from orgs.interfaces import OrgPostBrief
    from posts.dtos import TimelineItem
    from posts.public_service import PublicPostService

router = APIRouter(tags=["posts"])


@router.get("/announcements", response_model=PublicTimelinePage)
def list_announcement_timeline(
    limit: int = Query(default=12, ge=1, le=30),
    cursor: str | None = Query(default=None),
    service: PublicPostService = Depends(get_public_post_service),
) -> PublicTimelinePage:
    """Global guest timeline of published announcements (no auth)."""
    page = service.list_timeline(parse_cursor(cursor), limit)
    return PublicTimelinePage(
        items=[_item(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


def _item(item: TimelineItem) -> PublicTimelineItem:
    return PublicTimelineItem(
        id=item.id,
        title=item.title,
        excerpt=item.excerpt,
        cover_url=item.cover_url,
        author_name=item.author_name,
        published_at=item.published_at,
        comment_count=item.comment_count,
        org=PublicTimelineOrg(
            id=item.org.id,
            name=item.org.name,
            slug=item.org.slug,
            logo_url=item.org.logo_url,
        ),
    )


def _teaser(brief: OrgPostBrief) -> PublicOrgPostItem:
    return PublicOrgPostItem(
        id=brief.id,
        title=brief.title,
        excerpt=brief.excerpt,
        cover_url=brief.cover_url,
        author_name=brief.author_name,
        published_at=brief.published_at,
        comment_count=brief.comment_count,
    )


@router.get(
    "/orgs/{slug}/announcements",
    response_model=PublicAnnouncementPage,
)
def list_public_announcements(
    slug: str,
    limit: int = Query(default=9, ge=1, le=30),
    page: int = Query(default=1, ge=1),
    service: PublicPostService = Depends(get_public_post_service),
) -> PublicAnnouncementPage:
    """Guest listing of published announcements for one org (no auth)."""
    listing = service.list_public_page(slug, limit=limit, page=page)
    return PublicAnnouncementPage(
        items=[_teaser(brief) for brief in listing.items],
        total=listing.total,
    )


@router.get(
    "/orgs/{slug}/announcements/{post_id}",
    response_model=PostResponse,
)
def get_public_announcement(
    slug: str,
    post_id: UUID,
    service: PublicPostService = Depends(get_public_post_service),
) -> PostResponse:
    """Guest read of one published announcement post (no auth)."""
    return to_post(service.get_public_post(slug, post_id))
