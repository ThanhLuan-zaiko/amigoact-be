"""Guest-facing org routes: public directory plus profile. No auth required."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from core.dependencies_features import get_public_org_service
from orgs.schemas import (
    BucketCount,
    OrgKind,
    OrgSort,
    PublicOrgActivityItem,
    PublicOrgDetailResponse,
    PublicOrgPage,
    PublicOrgPostItem,
    PublicOrgResponse,
)

if TYPE_CHECKING:
    from orgs.listing import PublicOrgDetail, PublicOrgSnapshot
    from orgs.public_service import PublicOrgService

router = APIRouter(tags=["orgs"])


def _public_schema(item: PublicOrgSnapshot) -> PublicOrgResponse:
    return PublicOrgResponse(
        id=item.id,
        name=item.name,
        slug=item.slug,
        description=item.description,
        kind=item.kind,  # type: ignore[arg-type]
        member_count=item.member_count,
        join_policy=item.join_policy,  # type: ignore[arg-type]
        city=item.city,
        country=item.country,
        verified_at=item.verified_at,
        logo_url=item.logo_url,
        cover_url=item.cover_url,
        created_at=item.created_at,
    )


@router.get("/orgs", response_model=PublicOrgPage)
def list_public_orgs(
    q: str | None = Query(default=None, max_length=100),
    kind: OrgKind | None = Query(default=None),
    sort: OrgSort = Query(default="newest"),
    limit: int = Query(default=24, ge=1, le=60),
    offset: int = Query(default=0, ge=0),
    service: PublicOrgService = Depends(get_public_org_service),
) -> PublicOrgPage:
    """Public directory: every live org, guest-readable (no auth)."""
    page = service.list_public_orgs(
        q=q, kind=kind, sort=sort, limit=limit, offset=offset
    )
    return PublicOrgPage(
        items=[_public_schema(item) for item in page.items],
        total=page.total,
        counts=[BucketCount(bucket=key, count=count) for key, count in page.counts],
    )


def _public_detail_schema(item: PublicOrgDetail) -> PublicOrgDetailResponse:
    return PublicOrgDetailResponse(
        id=item.id,
        name=item.name,
        slug=item.slug,
        description=item.description,
        kind=item.kind,  # type: ignore[arg-type]
        member_count=item.member_count,
        join_policy=item.join_policy,  # type: ignore[arg-type]
        email=item.email,
        phone=item.phone,
        website=item.website,
        address=item.address,
        city=item.city,
        country=item.country,
        legal_status=item.legal_status,
        legal_name=item.legal_name,
        license_number=item.license_number,
        tax_code=item.tax_code,
        verified_at=item.verified_at,
        logo_url=item.logo_url,
        cover_url=item.cover_url,
        gallery=item.gallery,
        activity_count=item.activity_count,
        activities=[
            PublicOrgActivityItem(
                id=activity.id,
                slug=activity.slug,
                title=activity.title,
                status=activity.status,
                city=activity.city,
                start_at=activity.start_at,
            )
            for activity in item.activities
        ],
        announcement_count=item.announcement_count,
        announcements=[
            PublicOrgPostItem(
                id=post.id,
                title=post.title,
                excerpt=post.excerpt,
                cover_url=post.cover_url,
                author_name=post.author_name,
                published_at=post.published_at,
                comment_count=post.comment_count,
            )
            for post in item.announcements
        ],
        created_at=item.created_at,
    )


@router.get("/orgs/{slug}", response_model=PublicOrgDetailResponse)
def get_public_org(
    slug: str,
    service: PublicOrgService = Depends(get_public_org_service),
) -> PublicOrgDetailResponse:
    """Guest profile: live org by slug with trust signals (no auth).

    Registered after the orgs router so /orgs/mine keeps winning over
    the {slug} path parameter.
    """
    return _public_detail_schema(service.get_public_org(slug))
