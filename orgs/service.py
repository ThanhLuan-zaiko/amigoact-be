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
from orgs.interfaces import MediaRepository, OrgRepository
from orgs.listing import OrgListResult, paginate_mine
from orgs.repository import generate_org_id

if TYPE_CHECKING:
    from orgs.model import Organization

_ORG_KINDS = ("organization", "club", "group", "business")
_JOIN_POLICIES = ("invite", "open")


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
    ) -> None:
        self._orgs = orgs
        self._media = media
        self._store = store

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
        )
        return self._snapshot(org.id)

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
    ) -> OrgSnapshot:
        """Owner renames, re-describes or re-policies a live org."""
        self._require_live(org_id, user_id)
        clean_name = name.strip()
        if not (2 <= len(clean_name) <= 100):
            raise InvalidBusinessProfileError("Org name is invalid.")
        if len(description.strip()) > 500:
            raise InvalidBusinessProfileError("Org description is invalid.")
        if join_policy is not None and join_policy not in _JOIN_POLICIES:
            raise InvalidBusinessProfileError("Join policy is invalid.")
        now = utcnow()
        org = self._orgs.update_details(
            org_id, clean_name, description.strip(), now, join_policy
        )
        assert org is not None
        return self._snapshot(org_id)

    def soft_delete_org(self, org_id: UUID, user_id: UUID) -> OrgSnapshot:
        """Owner moves an org to trash. Restorable, files stay on disk."""
        self._require_live(org_id, user_id)
        org = self._orgs.mark_deleted(org_id, utcnow())
        assert org is not None
        return self._snapshot(org_id)

    def restore_org(self, org_id: UUID, user_id: UUID) -> OrgSnapshot:
        """Owner brings a soft-deleted org back to the visible list."""
        org = self._require_owner(org_id, user_id)
        if getattr(org, "deleted_at", None) is None:
            raise InvalidBusinessProfileError("Organization is not deleted.")
        restored = self._orgs.mark_restored(org_id, utcnow())
        assert restored is not None
        return self._snapshot(org_id)

    def hard_delete_org(self, org_id: UUID, user_id: UUID) -> int:
        """Owner erases everything: rows plus the org folder and orphans."""
        self._require_owner(org_id, user_id)
        removed = self._orgs.delete_everything(org_id)
        swept = 0
        if self._store is not None:
            self._store.delete_org_dir(org_id)
            known = self._media.known_org_ids() if self._media is not None else set()
            swept = self._store.sweep_orphans(set(known))
        return swept if removed else 0
