"""Public org read surface: guest directory plus profile. No auth, no CQL."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import NotFoundError
from core.media import media_kind
from orgs.interfaces import (
    ActivityDirectory,
    MediaRepository,
    OrgRepository,
    PostDirectory,
    UserDirectory,
)
from orgs.listing import (
    OrgMediaBrief,
    PublicOrgDetail,
    PublicOrgListResult,
    PublicOrgSnapshot,
    paginate_public,
)

if TYPE_CHECKING:
    from orgs.model import Organization

_MEDIA_LIST_LIMIT = 100


class PublicOrgService:
    """Read-only guest surface; only public-safe fields ever leave here."""

    def __init__(
        self,
        orgs: OrgRepository,
        media: MediaRepository | None = None,
        activities: ActivityDirectory | None = None,
        posts: PostDirectory | None = None,
        users: UserDirectory | None = None,
    ) -> None:
        self._orgs = orgs
        self._media = media
        self._activities = activities
        self._posts = posts
        self._users = users

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
        brief = (
            self._users.get_brief(org.owner_id)
            if self._users is not None
            else None
        )
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
            owner_name=brief.full_name if brief else None,
            owner_avatar_url=self._media_url(
                getattr(brief, "avatar_media_id", None)
            ),
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
        page = paginate_public(
            snapshots, q=q, kind=kind, sort=sort, limit=limit, offset=offset
        )
        # Media previews attach after the slice so only the visible page
        # pays the per-org gallery reads.
        items = []
        for item in page.items:
            preview, count = self._media_preview(item.id)
            items.append(replace(item, media=preview, media_count=count))
        return PublicOrgListResult(
            items=items, total=page.total, counts=page.counts
        )

    def _media_preview(
        self, org_id: UUID, limit: int = 6
    ) -> tuple[list[OrgMediaBrief], int]:
        """Cover-first public media strip plus the eligible total count.

        Only gallery/cover roles leave the server: logos already render as
        the card avatar fallback, attachments stay inside their posts.
        """
        if self._media is None:
            return [], 0
        covers: list[OrgMediaBrief] = []
        gallery: list[OrgMediaBrief] = []
        for asset in self._media.list_by_org(org_id):
            role = getattr(asset, "role", None) or "gallery"
            if role not in ("gallery", "cover"):
                continue
            if (asset.upload_status or "active") != "active":
                continue
            if getattr(asset, "deleted_at", None) is not None:
                continue
            kind = media_kind(asset.mime or "")
            if kind is None:
                continue
            brief = OrgMediaBrief(
                url=f"/media/{asset.file_url}",
                kind=kind,
                mime=asset.mime or "",
            )
            (covers if role == "cover" else gallery).append(brief)
        ordered = covers + gallery
        return ordered[:limit], len(ordered)

    def list_public_media(self, slug: str) -> list[OrgMediaBrief]:
        """Complete cover-first media list for the in-feed lightbox.

        Unlike the profile gallery strip this keeps videos and has no
        eight-item cap; attachments and brand-only assets stay out.
        """
        org = self._orgs.get_by_slug(slug.strip().lower())
        if (
            org is None
            or org.deleted_at is not None
            or (getattr(org, "status", "active") or "active") != "active"
        ):
            raise NotFoundError("Organization not found.")
        media, _ = self._media_preview(org.id, limit=_MEDIA_LIST_LIMIT)
        return media

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
