"""Platform-admin business rules: org verification plus role grants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from admin.interfaces import PlatformRoleStore
from core.exceptions import (
    ForbiddenError,
    InvalidOrgStateError,
    NotFoundError,
    UserNotFoundError,
)
from core.security import utcnow
from notifications.interfaces import NotificationPort
from orgs.interfaces import OrgDirectoryEvents, OrgRepository, UserDirectory
from rbac.catalog import PLATFORM_ADMIN_ROLE_ID
from rbac.interfaces import AccessControl

_LEGAL_STATUSES = ("pending", "verified", "rejected", "none")


@dataclass(frozen=True)
class AdminOrgSnapshot:
    """Queue row joined with owner display fields."""

    id: UUID
    name: str
    slug: str
    kind: str
    status: str
    legal_status: str
    tax_code: str | None
    legal_rep_name: str | None
    owner_id: UUID
    owner_name: str
    owner_email: str
    verified_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class AdminUserSnapshot:
    """One platform administrator with display fields."""

    user_id: UUID
    full_name: str
    email: str


class AdminService:
    """Verification queue consumption and platform role management."""

    def __init__(
        self,
        orgs: OrgRepository,
        platform_roles: PlatformRoleStore,
        users: UserDirectory,
        notifications: NotificationPort,
        access: AccessControl,
        admin_emails: frozenset[str] = frozenset(),
        directory_events: OrgDirectoryEvents | None = None,
    ) -> None:
        self._orgs = orgs
        self._roles = platform_roles
        self._users = users
        self._notifications = notifications
        self._access = access
        self._emails = admin_emails
        self._directory_events = directory_events

    def is_admin(self, user_id: UUID, email: str) -> bool:
        """Env bootstrap list or a live platform_admin grant."""
        if email.lower() in self._emails:
            return True
        return self._roles.has_role(user_id, PLATFORM_ADMIN_ROLE_ID)

    def _require_admin(self, user_id: UUID, email: str) -> None:
        if not self.is_admin(user_id, email):
            raise ForbiddenError("Platform administrator role required.")

    def _item(self, org) -> AdminOrgSnapshot:  # noqa: ANN001
        brief = self._users.get_brief(org.owner_id)
        return AdminOrgSnapshot(
            id=org.id,
            name=org.name,
            slug=org.slug,
            kind=org.org_type,
            status=org.status or "active",
            legal_status=org.legal_status or "none",
            tax_code=org.tax_code,
            legal_rep_name=org.legal_rep_name,
            owner_id=org.owner_id,
            owner_name=brief.full_name if brief else "",
            owner_email=brief.email if brief else "",
            verified_at=org.verified_at,
            created_at=org.created_at,
        )

    def list_orgs(
        self,
        actor_id: UUID,
        actor_email: str,
        *,
        status: str = "pending",
        limit: int = 50,
    ) -> list[AdminOrgSnapshot]:
        """Read one bucket of the verification queue (admin only)."""
        self._require_admin(actor_id, actor_email)
        if status not in _LEGAL_STATUSES:
            raise InvalidOrgStateError("Legal status filter is invalid.")
        return [
            self._item(org)
            for org in self._orgs.list_by_legal_status(status, limit)
        ]

    def _transition(
        self,
        actor_id: UUID,
        org_id: UUID,
        target: str,
        action: str,
        title: str,
        body: str,
    ) -> AdminOrgSnapshot:
        org = self._orgs.get_by_id(org_id)
        if org is None or org.deleted_at is not None:
            raise NotFoundError("Organization not found.")
        if (org.legal_status or "none") != "pending":
            raise InvalidOrgStateError(
                "Organization is not pending verification."
            )
        now = utcnow()
        verified = target == "verified"
        fresh = self._orgs.set_legal_status(
            org_id,
            target,
            verified_at=now if verified else None,
            verified_by=actor_id if verified else None,
            now=now,
        )
        assert fresh is not None
        if self._directory_events is not None:
            self._directory_events.directory_changed(
                "updated", org_id, fresh.slug
            )
        self._access.record(
            org_id, actor_id, action, "organization", org_id, "allowed"
        )
        try:
            self._notifications.notify(
                org.owner_id, "organization", title, body
            )
        except Exception:  # noqa: BLE001 - notifications are best-effort
            pass
        return self._item(fresh)

    def verify_org(
        self, actor_id: UUID, actor_email: str, org_id: UUID
    ) -> AdminOrgSnapshot:
        """Admin approves a business org's legal dossier."""
        self._require_admin(actor_id, actor_email)
        return self._transition(
            actor_id,
            org_id,
            "verified",
            "org.verify",
            "T\u1ed5 ch\u1ee9c \u0111\u00e3 \u0111\u01b0\u1ee3c x\u00e1c minh",
            "H\u1ed3 s\u01a1 ph\u00e1p l\u00fd c\u1ee7a t\u1ed5 ch\u1ee9c \u0111\u00e3 \u0111\u01b0\u1ee3c ban qu\u1ea3n tr\u1ecb ph\u00ea duy\u1ec7t.",
        )

    def reject_org(
        self, actor_id: UUID, actor_email: str, org_id: UUID, reason: str
    ) -> AdminOrgSnapshot:
        """Admin rejects a business org's legal dossier with a reason."""
        self._require_admin(actor_id, actor_email)
        return self._transition(
            actor_id,
            org_id,
            "rejected",
            "org.reject",
            "T\u1ed5 ch\u1ee9c ch\u01b0a \u0111\u01b0\u1ee3c x\u00e1c minh",
            reason or "H\u1ed3 s\u01a1 ph\u00e1p l\u00fd ch\u01b0a \u0111\u1ea1t y\u00eau c\u1ea7u, vui l\u00f2ng c\u1eadp nh\u1eadt.",
        )

    def list_admins(
        self, actor_id: UUID, actor_email: str
    ) -> list[AdminUserSnapshot]:
        """Roster of granted platform admins (env emails stay hidden)."""
        self._require_admin(actor_id, actor_email)
        items: list[AdminUserSnapshot] = []
        for user_id in self._roles.list_holders(PLATFORM_ADMIN_ROLE_ID):
            brief = self._users.get_brief(user_id)
            if brief is not None:
                items.append(
                    AdminUserSnapshot(
                        user_id=brief.id,
                        full_name=brief.full_name,
                        email=brief.email,
                    )
                )
        return items

    def grant_admin(
        self, actor_id: UUID, actor_email: str, target_id: UUID
    ) -> None:
        """Promote an account to platform administrator."""
        self._require_admin(actor_id, actor_email)
        if self._users.get_brief(target_id) is None:
            raise UserNotFoundError("User not found.")
        self._roles.grant(
            target_id, PLATFORM_ADMIN_ROLE_ID, actor_id, utcnow()
        )

    def grant_admin_by_email(
        self, actor_id: UUID, actor_email: str, target_email: str
    ) -> None:
        """Promote by email (the UI never sees raw user ids)."""
        self._require_admin(actor_id, actor_email)
        brief = self._users.find_by_email(target_email.strip().lower())
        if brief is None:
            raise UserNotFoundError("User not found.")
        self._roles.grant(
            brief.id, PLATFORM_ADMIN_ROLE_ID, actor_id, utcnow()
        )

    def revoke_admin(
        self, actor_id: UUID, actor_email: str, target_id: UUID
    ) -> None:
        """Demote a platform administrator (self-demotion allowed)."""
        self._require_admin(actor_id, actor_email)
        self._roles.revoke(target_id, PLATFORM_ADMIN_ROLE_ID)
