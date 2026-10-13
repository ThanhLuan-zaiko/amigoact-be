"""Public org read surface: guest directory plus profile. No auth, no CQL."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import NotFoundError
from orgs.interfaces import (
    ActivityDirectory,
    MediaRepository,
    OrgRepository,
    PostDirectory,
)
from orgs.listing import (
    PublicOrgDetail,
    PublicOrgListResult,
    PublicOrgSnapshot,
    paginate_public,
)

if TYPE_CHECKING:
    from orgs.model import Organization


class PublicOrgService:
    """Read-only guest surface; only public-safe fields ever leave here."""

    def __init__(
        self,
        orgs: OrgRepository,
        media: MediaRepository | None = None,
        activities: ActivityDirectory | None = None,
        posts: PostDirectory | None = None,
    ) -> None:
        self._orgs = orgs
        self._media = media
        self._activities = activities
        self._posts = posts

    def _media_url(self, asset_id: UUID | None) -> str | None:
        """Resolve a brand asset to its semi-public /media/ URL."""
        if asset_id is None or self._media is None:
            return None
        asset = self._media.get_asset(asset_id)
        if asset is None:
            return None
        return f"/media/{asset.file_url}"

    def _public_snapshot(self, org: Organization) -> PublicOrgSnapshot:
        """Card fields only; legal/contact data never leaves the server."""
        return PublicOrgSnapshot(
            id=org.id,
            name=org.name,
            slug=org.slug,
            description=org.description or "",
            kind=org.org_type,
            member_count=self._orgs.count_members(org.id),
            join_policy=getattr(org, "join_policy", None) or "invite",
            city=getattr(org, "city", None),
            country=getattr(org, "country", None),
            verified_at=getattr(org, "verified_at", None),
            logo_url=self._media_url(getattr(org, "logo_media_id", None)),
            cover_url=self._media_url(getattr(org, "cover_media_id", None)),
            created_at=org.created_at,
        )

    def list_public_orgs(
        self,
        *,
        q: str | None = None,
        kind: str | None = None,
        sort: str = "newest",
        limit: int = 24,
        offset: int = 0,
    ) -> PublicOrgListResult:
        """Guest directory: every live org, searched/sorted in memory."""
        snapshots = [
            self._public_snapshot(org) for org in self._orgs.list_public()
        ]
        return paginate_public(
            snapshots, q=q, kind=kind, sort=sort, limit=limit, offset=offset
        )

    def _gallery_urls(self, org_id: UUID, limit: int = 8) -> list[str]:
        """Newest gallery-role image URLs for the public profile strip."""
        if self._media is None:
            return []
        return [
            f"/media/{asset.file_url}"
            for asset in self._media.list_by_org(org_id)
            if asset.role == "gallery"
            and (asset.upload_status or "active") == "active"
            and getattr(asset, "deleted_at", None) is None
            and (asset.mime or "").startswith("image/")
        ][:limit]

    def get_public_org(self, slug: str) -> PublicOrgDetail:
        """Guest profile: live org by slug with trust signals, 404 else."""
        org = self._orgs.get_by_slug(slug.strip().lower())
        if (
            org is None
            or org.deleted_at is not None
            or (getattr(org, "status", "active") or "active") != "active"
        ):
            raise NotFoundError("Organization not found.")
        listing = (
            self._activities.list_public(org.id)
            if self._activities is not None
            else None
        )
        announcements = (
            self._posts.list_public(org.id)
            if self._posts is not None
            else None
        )
        return PublicOrgDetail(
            id=org.id,
            name=org.name,
            slug=org.slug,
            description=org.description or "",
            kind=org.org_type,
            member_count=self._orgs.count_members(org.id),
            join_policy=getattr(org, "join_policy", None) or "invite",
            email=getattr(org, "email", None),
            phone=getattr(org, "phone", None),
            website=getattr(org, "website", None),
            address=getattr(org, "address", None),
            city=getattr(org, "city", None),
            country=getattr(org, "country", None),
            legal_status=getattr(org, "legal_status", None) or "none",
            legal_name=getattr(org, "legal_name", None),
            license_number=getattr(org, "license_number", None),
            tax_code=getattr(org, "tax_code", None),
            verified_at=getattr(org, "verified_at", None),
            logo_url=self._media_url(getattr(org, "logo_media_id", None)),
            cover_url=self._media_url(getattr(org, "cover_media_id", None)),
            gallery=self._gallery_urls(org.id),
            activity_count=listing.total if listing is not None else 0,
            activities=listing.items if listing is not None else [],
            announcement_count=(
                announcements.total if announcements is not None else 0
            ),
            announcements=(
                announcements.items if announcements is not None else []
            ),
            created_at=org.created_at,
        )
