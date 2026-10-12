"""Org business rules. No FastAPI, no CQL strings here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import (
    ForbiddenError,
    InvalidBusinessProfileError,
    NotFoundError,
    OrgDeletedError,
)
from core.media import MediaStore
from core.security import utcnow
from orgs.interfaces import (
    ORG_KINDS,
    MediaRepository,
    OrgContactDetails,
    OrgDirectoryEvents,
    OrgRepository,
)
from orgs.listing import OrgListResult, paginate_mine
from orgs.repository import generate_org_id
from rbac.interfaces import AccessControl

if TYPE_CHECKING:
    from orgs.model import Organization

_ORG_KINDS = ORG_KINDS
_JOIN_POLICIES = ("invite", "open")
_CONTACT_LIMITS = {
    "email": 254,
    "phone": 20,
    "website": 255,
    "address": 255,
    "city": 100,
    "country": 100,
    "legal_name": 255,
    "license_number": 100,
}


@dataclass(frozen=True)
class OrgSnapshot:
    """Created org plus live member count for the response card."""

    id: UUID
    owner_id: UUID
    name: str
    slug: str
    description: str
    kind: str
    tax_code: str | None
    legal_rep_name: str | None
    legal_rep_id: str | None
    legal_rep_position: str | None
    legal_status: str
    status: str
    join_policy: str
    email: str | None
    phone: str | None
    website: str | None
    address: str | None
    city: str | None
    country: str | None
    legal_name: str | None
    license_number: str | None
    is_personal: bool
    logo_media_id: UUID | None
    cover_media_id: UUID | None
    verified_at: datetime | None
    previous_slug: str | None
    deleted_at: datetime | None
    member_count: int
    created_at: datetime


class OrgService:
    """Org CRUD with soft/hard delete plus org folder cleanup."""

    def __init__(
        self,
        orgs: OrgRepository,
        media: MediaRepository | None = None,
        store: MediaStore | None = None,
        events: OrgDirectoryEvents | None = None,
        access: AccessControl | None = None,
    ) -> None:
        self._orgs = orgs
        self._media = media
        self._store = store
        self._events = events
        self._access = access

    def _emit(self, action: str, org_id: UUID, slug: str) -> None:
        """Best-effort public directory fan-out after a mutation commits."""
        if self._events is not None:
            self._events.directory_changed(action, org_id, slug)

    def _snapshot(self, org_id: UUID) -> OrgSnapshot:
        org = self._orgs.get_by_id(org_id)
        assert org is not None
        return OrgSnapshot(
            id=org.id,
            owner_id=org.owner_id,
            name=org.name,
            slug=org.slug,
            description=org.description or "",
            kind=org.org_type,
            tax_code=org.tax_code,
            legal_rep_name=org.legal_rep_name,
            legal_rep_id=org.legal_rep_id,
            legal_rep_position=org.legal_rep_position,
            legal_status=org.legal_status,
            status=getattr(org, "status", "active") or "active",
            join_policy=getattr(org, "join_policy", None) or "invite",
            email=getattr(org, "email", None),
            phone=getattr(org, "phone", None),
            website=getattr(org, "website", None),
            address=getattr(org, "address", None),
            city=getattr(org, "city", None),
            country=getattr(org, "country", None),
            legal_name=getattr(org, "legal_name", None),
            license_number=getattr(org, "license_number", None),
            is_personal=bool(getattr(org, "is_personal", False)),
            logo_media_id=getattr(org, "logo_media_id", None),
            cover_media_id=getattr(org, "cover_media_id", None),
            verified_at=getattr(org, "verified_at", None),
            previous_slug=getattr(org, "previous_slug", None),
            deleted_at=getattr(org, "deleted_at", None),
            member_count=self._orgs.count_members(org.id),
            created_at=org.created_at,
        )

    def _owned(self, org_id: UUID) -> Organization:
        """Load an org or 404."""
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        return org

    def _require_owner(self, org_id: UUID, user_id: UUID) -> Organization:
        org = self._owned(org_id)
        if org.owner_id != user_id:
            raise ForbiddenError("Only the org owner can do this.")
        return org

    def _require_live(self, org_id: UUID, user_id: UUID) -> Organization:
        org = self._require_owner(org_id, user_id)
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        return org

    def _require_editor(self, org_id: UUID, user_id: UUID) -> Organization:
        """Owner, or an active member holding the org:update permission."""
        org = self._owned(org_id)
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        if org.owner_id == user_id:
            return org
        if (
            self._access is not None
            and self._orgs.is_member(org_id, user_id)
            and self._access.has_permission(org_id, user_id, "org:update")
        ):
            return org
        raise ForbiddenError("Only the org owner can do this.")

    def create_org(
        self,
        owner_id: UUID,
        name: str,
        slug: str,
        description: str,
        kind: str,
        join_policy: str = "invite",
        tax_code: str | None = None,
        legal_rep_name: str | None = None,
        legal_rep_id: str | None = None,
        legal_rep_position: str | None = None,
        contact: OrgContactDetails | None = None,
    ) -> OrgSnapshot:
        """Create an org. Business kind pins tax plus legal head."""
        clean_name = name.strip()
        clean_slug = slug.strip().lower()
        if kind not in _ORG_KINDS:
            raise InvalidBusinessProfileError("Org kind is invalid.")
        if join_policy not in _JOIN_POLICIES:
            raise InvalidBusinessProfileError("Join policy is invalid.")
        if not (2 <= len(clean_name) <= 100):
            raise InvalidBusinessProfileError("Org name is invalid.")
        if kind == "business" and not (tax_code and legal_rep_name and legal_rep_id):
            raise InvalidBusinessProfileError(
                "Business orgs require tax_code and legal representative."
            )
        legal_status = "pending" if kind == "business" else "none"
        now = utcnow()
        org = self._orgs.create(
            generate_org_id(),
            owner_id,
            clean_name,
            clean_slug,
            description.strip(),
            kind,
            join_policy,
            tax_code,
            legal_rep_name,
            legal_rep_id,
            legal_rep_position,
            legal_status,
            now,
            self._clean_contact(contact),
        )
        self._emit("created", org.id, org.slug)
        return self._snapshot(org.id)

    @staticmethod
    def _clean_contact(
        contact: OrgContactDetails | None,
    ) -> OrgContactDetails | None:
        """Trim contact strings and enforce column length limits."""
        if contact is None:
            return None
        cleaned: dict[str, object] = {}
        for field_name, limit in _CONTACT_LIMITS.items():
            value = getattr(contact, field_name)
            if isinstance(value, str):
                value = value.strip() or None
            if value is not None and len(value) > limit:
                raise InvalidBusinessProfileError(
                    f"Org {field_name.replace('_', ' ')} is invalid."
                )
            cleaned[field_name] = value
        return OrgContactDetails(is_personal=contact.is_personal, **cleaned)

    def list_my_orgs(
        self,
        user_id: UUID,
        include_deleted: bool = False,
        *,
        q: str | None = None,
        status: str | None = None,
        sort: str = "newest",
        limit: int = 20,
        offset: int = 0,
    ) -> OrgListResult:
        """List, search, filter, sort and page one user's orgs."""
        snapshots = [self._snapshot(org.id) for org in self._orgs.list_by_user(user_id)]
        if not include_deleted:
            snapshots = [item for item in snapshots if item.deleted_at is None]
        return paginate_mine(
            snapshots, q=q, status=status, sort=sort, limit=limit, offset=offset
        )

    def update_org(
        self,
        org_id: UUID,
        user_id: UUID,
        name: str,
        description: str,
        join_policy: str | None = None,
        contact: OrgContactDetails | None = None,
    ) -> OrgSnapshot:
        """Owner or org:update holder edits profile/policy of a live org."""
        self._require_editor(org_id, user_id)
        clean_name = name.strip()
        if not (2 <= len(clean_name) <= 100):
            raise InvalidBusinessProfileError("Org name is invalid.")
        if len(description.strip()) > 500:
            raise InvalidBusinessProfileError("Org description is invalid.")
        if join_policy is not None and join_policy not in _JOIN_POLICIES:
            raise InvalidBusinessProfileError("Join policy is invalid.")
        now = utcnow()
        org = self._orgs.update_details(
            org_id,
            clean_name,
            description.strip(),
            now,
            join_policy,
            self._clean_contact(contact),
        )
        assert org is not None
        self._emit("updated", org_id, org.slug)
        return self._snapshot(org_id)

    def soft_delete_org(self, org_id: UUID, user_id: UUID) -> OrgSnapshot:
        """Owner moves an org to trash. Restorable, files stay on disk."""
        self._require_live(org_id, user_id)
        org = self._orgs.mark_deleted(org_id, utcnow())
        assert org is not None
        self._emit("removed", org_id, org.slug)
        return self._snapshot(org_id)

    def restore_org(self, org_id: UUID, user_id: UUID) -> OrgSnapshot:
        """Owner brings a soft-deleted org back to the visible list."""
        org = self._require_owner(org_id, user_id)
        if getattr(org, "deleted_at", None) is None:
            raise InvalidBusinessProfileError("Organization is not deleted.")
        restored = self._orgs.mark_restored(org_id, utcnow())
        assert restored is not None
        self._emit("restored", org_id, restored.slug)
        return self._snapshot(org_id)

    def hard_delete_org(self, org_id: UUID, user_id: UUID) -> int:
        """Owner erases everything: rows plus the org folder and orphans."""
        org = self._require_owner(org_id, user_id)
        removed = self._orgs.delete_everything(org_id)
        if removed:
            self._emit("removed", org_id, org.slug)
        swept = 0
        if self._store is not None:
            self._store.delete_org_dir(org_id)
            known = self._media.known_org_ids() if self._media is not None else set()
            swept = self._store.sweep_orphans(set(known))
        return swept if removed else 0
