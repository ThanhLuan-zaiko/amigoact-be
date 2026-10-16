"""Abstract ports for the orgs bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from orgs.model import MediaAsset, MemberByUser, Organization, OrganizationMember


ORG_KINDS: tuple[str, ...] = ("organization", "club", "group", "business")
"""Every org kind; also the partition set of the public directory feed."""


@dataclass(frozen=True)
class UserBrief:
    """Minimal user fields other features may render (auth owns users)."""

    id: UUID
    full_name: str
    email: str
    status: str
    avatar_media_id: UUID | None = None


@dataclass(frozen=True)
class OrgContactDetails:
    """Optional contact/legal fields written as a full-replace set."""

    email: str | None = None
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    legal_name: str | None = None
    license_number: str | None = None
    is_personal: bool = False


@dataclass(frozen=True)
class OrgLegalEdit:
    """PATCH-provided legal identity; `provided` marks explicitly sent keys."""

    tax_code: str | None = None
    legal_rep_name: str | None = None
    legal_rep_id: str | None = None
    legal_rep_position: str | None = None
    provided: frozenset[str] = frozenset()


class OrgRepository(ABC):
    """Persistence port for orgs plus slug uniqueness and memberships."""

    @abstractmethod
    def create(
        self,
        org_id: UUID,
        owner_id: UUID,
        name: str,
        slug: str,
        description: str,
        kind: str,
        join_policy: str,
        tax_code: str | None,
        legal_rep_name: str | None,
        legal_rep_id: str | None,
        legal_rep_position: str | None,
        legal_status: str,
        now: datetime,
        contact: OrgContactDetails | None = None,
    ) -> Organization:
        """Claim slug/tax code with LWT, then insert org plus owner row."""

    @abstractmethod
    def get_by_id(self, org_id: UUID) -> Organization | None:
        """Load an org by primary key."""

    @abstractmethod
    def get_by_slug(self, slug: str) -> Organization | None:
        """Load an org through the slug index."""

    @abstractmethod
    def list_by_user(self, user_id: UUID) -> list[Organization]:
        """List every org a user actively belongs to via the member index."""

    @abstractmethod
    def count_members(self, org_id: UUID) -> int:
        """Count active membership rows for one org."""

    @abstractmethod
    def is_member(self, org_id: UUID, user_id: UUID) -> bool:
        """Single-row membership check for upload and gallery reads."""

    @abstractmethod
    def update_details(
        self,
        org_id: UUID,
        name: str,
        description: str,
        now: datetime,
        join_policy: str | None = None,
        contact: OrgContactDetails | None = None,
        legal: dict[str, object] | None = None,
    ) -> Organization | None:
        """Replace name/description (and policy/contact/legal), fresh row out."""

    @abstractmethod
    def mark_deleted(self, org_id: UUID, now: datetime) -> Organization | None:
        """Soft delete: stamp deleted_at, free slug, keep rows for restore."""

    @abstractmethod
    def mark_restored(self, org_id: UUID, now: datetime) -> Organization | None:
        """Clear deleted_at, reclaim the slug (suffix fallback if taken)."""

    @abstractmethod
    def set_brand_media(
        self, org_id: UUID, role: str, asset_id: UUID | None, now: datetime
    ) -> None:
        """Point cover_media_id/logo_media_id at an asset (or clear it)."""

    @abstractmethod
    def list_by_legal_status(
        self, legal_status: str, limit: int = 100
    ) -> list[Organization]:
        """Verification queue read: orgs under one legal_status, oldest first."""

    @abstractmethod
    def list_public(self) -> list[Organization]:
        """Public directory read: every live org across all kind feeds."""

    @abstractmethod
    def set_legal_status(
        self,
        org_id: UUID,
        legal_status: str,
        verified_at: datetime | None,
        verified_by: UUID | None,
        now: datetime,
    ) -> Organization | None:
        """Move the org to a new legal status and re-partition its queue row."""

    @abstractmethod
    def delete_everything(self, org_id: UUID) -> bool:
        """Hard delete: drop org, slug index, memberships and media rows."""


class MediaRepository(ABC):
    """Persistence port for org gallery metadata (bytes live in MediaStore)."""

    @abstractmethod
    def create_asset(
        self,
        asset_id: UUID,
        org_id: UUID,
        file_url: str,
        mime: str,
        size_bytes: int,
        now: datetime,
        role: str = "gallery",
        file_hash: str | None = None,
        uploader_id: UUID | None = None,
        original_name: str | None = None,
        owner_type: str = "organization",
    ) -> MediaAsset:
        """Insert the metadata row plus the owner/uploader/hash feeds."""

    @abstractmethod
    def list_by_org(self, org_id: UUID) -> list[MediaAsset]:
        """Newest-first gallery rows for one org."""

    @abstractmethod
    def get_asset(self, asset_id: UUID) -> MediaAsset | None:
        """Load one asset by primary key."""

    @abstractmethod
    def set_role(self, asset_id: UUID, role: str) -> MediaAsset | None:
        """Update the gallery/cover/logo role, return the fresh row."""

    @abstractmethod
    def replace_content(
        self,
        asset_id: UUID,
        file_url: str,
        mime: str,
        size_bytes: int,
        file_hash: str | None,
        original_name: str | None,
        now: datetime,
    ) -> MediaAsset | None:
        """Swap stored file metadata after a byte rewrite; feeds stay in sync."""

    @abstractmethod
    def delete_asset(self, asset_id: UUID) -> MediaAsset | None:
        """Remove metadata rows, return the removed row for file cleanup."""

    @abstractmethod
    def set_upload_status(self, asset_id: UUID, status: str) -> None:
        """Flip active/rejected visibility after moderation review."""

    @abstractmethod
    def known_org_ids(self) -> set[str]:
        """Every org id owning a folder, used for orphan sweeps."""


class MemberRepository(ABC):
    """Persistence port for the dual membership tables."""

    @abstractmethod
    def get(self, org_id: UUID, user_id: UUID) -> OrganizationMember | None:
        """Load one membership row."""

    @abstractmethod
    def list_by_org(self, org_id: UUID) -> list[OrganizationMember]:
        """Every membership row of one org (all statuses)."""

    @abstractmethod
    def list_links_by_user(self, user_id: UUID) -> list[MemberByUser]:
        """Every membership link one user holds (all statuses)."""

    @abstractmethod
    def put(
        self,
        org_id: UUID,
        user_id: UUID,
        status: str,
        now: datetime,
        invited_by: UUID | None = None,
    ) -> OrganizationMember:
        """Insert both membership rows for a fresh lifecycle."""

    @abstractmethod
    def set_status(
        self,
        org_id: UUID,
        user_id: UUID,
        status: str,
        now: datetime,
        invited_by: UUID | None = None,
    ) -> OrganizationMember | None:
        """Dual-write a status transition; invited_by None keeps existing."""


class UserDirectory(ABC):
    """Read-only user lookup port (auth owns the users tables)."""

    @abstractmethod
    def get_brief(self, user_id: UUID) -> UserBrief | None:
        """Load display fields for one user."""

    @abstractmethod
    def find_by_email(self, email: str) -> UserBrief | None:
        """Resolve an account by email (invite lookups)."""


@dataclass(frozen=True)
class OrgActivityBrief:
    """Public card fields of one org activity (activities owns the rows)."""

    id: UUID
    slug: str
    title: str
    status: str
    city: str | None
    start_at: datetime | None


@dataclass(frozen=True)
class OrgActivityListing:
    """Public-status activity briefs plus their exact total count."""

    total: int
    items: list[OrgActivityBrief]


class ActivityDirectory(ABC):
    """Read-only bridge onto the activities context (activities owns rows)."""

    @abstractmethod
    def list_public(self, org_id: UUID, limit: int = 6) -> OrgActivityListing:
        """Newest public-status activities of one org, sliced, plus total."""


@dataclass(frozen=True)
class OrgPostBrief:
    """Public card fields of one published announcement (posts owns rows)."""

    id: UUID
    title: str
    excerpt: str
    cover_url: str | None
    author_name: str
    published_at: datetime | None
    comment_count: int


@dataclass(frozen=True)
class OrgPostListing:
    """Published announcement briefs plus their exact total count."""

    total: int
    items: list[OrgPostBrief]


class PostDirectory(ABC):
    """Read-only bridge onto the posts context (posts owns the rows)."""

    @abstractmethod
    def list_public(self, org_id: UUID, limit: int = 4) -> OrgPostListing:
        """Newest published announcements of one org, sliced, plus total."""


class MemberEvents(ABC):
    """Realtime fan-out port for roster and invitation changes (best-effort)."""

    @abstractmethod
    def member_changed(
        self,
        org_id: UUID,
        action: str,
        target_id: UUID,
        actor_id: UUID,
        detail: str | None = None,
    ) -> None:
        """Broadcast one roster change to members:{org_id} subscribers."""

    @abstractmethod
    def inbox_changed(
        self,
        user_id: UUID,
        action: str,
        org_id: UUID,
        detail: str | None = None,
    ) -> None:
        """Push to notifications:{user_id} so an invitee updates live."""


class OrgDirectoryEvents(ABC):
    """Public directory fan-out for guests on orgs:directory (best-effort)."""

    @abstractmethod
    def directory_changed(self, action: str, org_id: UUID, slug: str) -> None:
        """Broadcast a visibility-affecting change; action is one of
        created/updated/restored/removed and the payload stays public-only."""
