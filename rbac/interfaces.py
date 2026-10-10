"""Abstract ports for the rbac bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from rbac.model import AccessAuditLog, Role, UserPermissionGrant, UserRole


class RoleRepository(ABC):
    """Persistence port for roles and org-scoped assignments."""

    @abstractmethod
    def get_role(self, role_id: UUID) -> Role | None:
        """Load one role by primary key."""

    @abstractmethod
    def resolve_role(self, org_id: UUID, name: str) -> Role | None:
        """Resolve a role name: system ids first, then org customs."""

    @abstractmethod
    def list_role_permissions(self, role_id: UUID) -> set[str]:
        """Every permission code attached to one role."""

    @abstractmethod
    def list_assignments(self, org_id: UUID, user_id: UUID) -> list[UserRole]:
        """Role rows one user holds inside one org."""

    @abstractmethod
    def list_org_assignments(self, org_id: UUID) -> list[UserRole]:
        """Every role assignment inside one org (roster rendering)."""

    @abstractmethod
    def assign_role(
        self,
        org_id: UUID,
        user_id: UUID,
        role_id: UUID,
        granted_by: UUID,
        now: datetime,
    ) -> None:
        """Dual-write the assignment into user_roles + roles_by_user."""

    @abstractmethod
    def revoke_role(self, org_id: UUID, user_id: UUID, role_id: UUID) -> None:
        """Drop the assignment rows on both query tables."""


class GrantRepository(ABC):
    """Persistence port for direct per-user permission grants."""

    @abstractmethod
    def get_grant(
        self, org_id: UUID, user_id: UUID, permission_code: str
    ) -> UserPermissionGrant | None:
        """Load one direct grant row."""


class AuditReader(ABC):
    """Read side of the append-only authorization trail."""

    @abstractmethod
    def list_for_org(
        self, org_id: UUID, limit: int
    ) -> list[AccessAuditLog]:
        """Newest-first audit rows for one org partition."""


class AuditWriter(ABC):
    """Append-only authorization trail writer."""

    @abstractmethod
    def record(
        self,
        org_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        result: str,
        now: datetime,
    ) -> None:
        """Append one audit row (allowed | denied)."""


class AccessControl(ABC):
    """Facade consumed by other features: check, render, mutate, audit."""

    @abstractmethod
    def has_permission(
        self, org_id: UUID, user_id: UUID, permission: str
    ) -> bool:
        """True when a live grant or assigned role covers the code."""

    @abstractmethod
    def role_names_of(self, org_id: UUID, user_id: UUID) -> list[str]:
        """Live role names one user holds inside one org."""

    @abstractmethod
    def role_map(self, org_id: UUID) -> dict[UUID, list[str]]:
        """User id to live role names for the whole org (list render)."""

    @abstractmethod
    def assign(
        self, org_id: UUID, actor_id: UUID, user_id: UUID, role_name: str
    ) -> None:
        """Grant a named role to a user (idempotent)."""

    @abstractmethod
    def revoke(self, org_id: UUID, user_id: UUID, role_name: str) -> None:
        """Revoke a named role from a user (idempotent)."""

    @abstractmethod
    def record(
        self,
        org_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        result: str,
    ) -> None:
        """Best-effort audit append; never breaks the caller."""
