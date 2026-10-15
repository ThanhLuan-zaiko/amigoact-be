"""Org audit feed: manager-scoped reads over access_audit_logs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from core.exceptions import ForbiddenError, NotFoundError
from orgs.interfaces import MemberRepository, OrgRepository, UserDirectory
from orgs.member_helpers import is_active_member
from rbac.interfaces import AccessControl, AuditReader


@dataclass(frozen=True)
class AuditEntry:
    """One audit row rendered for the org manager feed."""

    log_id: UUID
    occurred_at: datetime
    actor_id: UUID
    actor_name: str
    action: str
    resource_type: str
    resource_id: UUID | None
    result: str
    detail: str | None


class AuditService:
    """Manager-only newest-first audit reads for one org."""

    def __init__(
        self,
        orgs: OrgRepository,
        members: MemberRepository,
        access: AccessControl,
        reader: AuditReader,
        users: UserDirectory,
    ) -> None:
        self._orgs = orgs
        self._members = members
        self._access = access
        self._reader = reader
        self._users = users

    def feed(
        self, org_id: UUID, viewer_id: UUID, limit: int = 50
    ) -> list[AuditEntry]:
        """Owner or member:view holder reads the org's audit trail."""
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        allowed = org.owner_id == viewer_id or (
            is_active_member(self._members, org_id, viewer_id)
            and self._access.has_permission(
                org_id, viewer_id, "member:view"
            )
        )
        if not allowed:
            raise ForbiddenError("Only org managers can view the audit log.")
        entries: list[AuditEntry] = []
        for row in self._reader.list_for_org(org_id, limit):
            brief = self._users.get_brief(row.actor_id)
            entries.append(
                AuditEntry(
                    log_id=row.log_id,
                    occurred_at=row.occurred_at,
                    actor_id=row.actor_id,
                    actor_name=(
                        brief.full_name
                        if brief is not None
                        else str(row.actor_id)[:8]
                    ),
                    action=row.action,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    result=row.result,
                    detail=getattr(row, "meta", None) or None,
                )
            )
        return entries
