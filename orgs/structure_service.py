"""Business rules for the org campus/department tree."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import ForbiddenError, InvalidBusinessProfileError, NotFoundError
from core.ids import uuid7
from orgs.interfaces import OrgRepository
from orgs.model import Campus, CampusByOrg, Department, DepartmentByOrg, OrgType
from orgs.structure_interfaces import OrgTypeStore, StructureStore
from profiles.interfaces import ProfileStore
from rbac.interfaces import AccessControl


class StructureService:
    """Manager-only writes; members can read the org structure."""

    def __init__(
        self,
        *,
        orgs: OrgRepository,
        structure: StructureStore,
        access: AccessControl,
        profiles: ProfileStore,
        types: OrgTypeStore,
    ) -> None:
        self._orgs = orgs
        self._structure = structure
        self._access = access
        self._profiles = profiles
        self._types = types

    def _require_updater(self, org_id: UUID, actor_id: UUID) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if org.owner_id != actor_id and not self._access.has_permission(
            org_id, actor_id, "org:update"
        ):
            raise ForbiddenError(
                "Only org managers can edit the structure."
            )

    def _require_viewer(self, org_id: UUID, actor_id: UUID) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if not self._orgs.is_member(org_id, actor_id):
            raise ForbiddenError("Only org members can view the structure.")

    def create_campus(
        self, org_id: UUID, actor_id: UUID, name: str, address: str | None
    ) -> Campus:
        self._require_updater(org_id, actor_id)
        if not name.strip():
            raise InvalidBusinessProfileError("Campus name is required.")
        return self._structure.create_campus(
            uuid7(), org_id, name.strip(), address
        )

    def list_campuses(
        self, org_id: UUID, actor_id: UUID
    ) -> list[CampusByOrg]:
        self._require_viewer(org_id, actor_id)
        return self._structure.list_campuses(org_id)

    def update_campus(
        self,
        org_id: UUID,
        campus_id: UUID,
        actor_id: UUID,
        name: str | None,
        address: str | None,
        status: str | None,
    ) -> Campus:
        self._require_updater(org_id, actor_id)
        row = self._structure.get_campus(campus_id)
        if row is None or row.org_id != org_id:
            raise NotFoundError("Campus not found.")
        new_name = (name or row.name or "").strip()
        if not new_name:
            raise InvalidBusinessProfileError("Campus name is required.")
        updated = self._structure.update_campus(
            campus_id,
            new_name,
            address if address is not None else row.address,
            status or row.status or "active",
        )
        assert updated is not None
        return updated

    def create_department(
        self,
        org_id: UUID,
        actor_id: UUID,
        name: str,
        code: str | None,
        campus_id: UUID | None,
    ) -> Department:
        self._require_updater(org_id, actor_id)
        if not name.strip():
            raise InvalidBusinessProfileError("Department name is required.")
        if campus_id is not None:
            campus = self._structure.get_campus(campus_id)
            if campus is None or campus.org_id != org_id:
                raise NotFoundError("Campus not found.")
        return self._structure.create_department(
            uuid7(), org_id, campus_id, name.strip(), code
        )

    def list_departments(
        self, org_id: UUID, actor_id: UUID
    ) -> list[DepartmentByOrg]:
        self._require_viewer(org_id, actor_id)
        return self._structure.list_departments(org_id)

    def update_department(
        self,
        org_id: UUID,
        department_id: UUID,
        actor_id: UUID,
        name: str | None,
        code: str | None,
        campus_id: UUID | None,
        status: str | None,
    ) -> Department:
        self._require_updater(org_id, actor_id)
        row = self._structure.get_department(department_id)
        if row is None or row.org_id != org_id:
            raise NotFoundError("Department not found.")
        if campus_id is not None:
            campus = self._structure.get_campus(campus_id)
            if campus is None or campus.org_id != org_id:
                raise NotFoundError("Campus not found.")
        new_name = (name or row.name or "").strip()
        if not new_name:
            raise InvalidBusinessProfileError("Department name is required.")
        updated = self._structure.update_department(
            department_id,
            campus_id if campus_id is not None else row.campus_id,
            new_name,
            code if code is not None else row.code,
            status or row.status or "active",
        )
        assert updated is not None
        return updated

    def lookup_student(
        self,
        org_id: UUID,
        actor_id: UUID,
        student_code: str,
        campus_id: UUID | None,
    ) -> UUID | None:
        """Resolve a student code for managers; campus optional."""
        self._require_updater(org_id, actor_id)
        code = student_code.strip()
        if not code:
            return None
        if campus_id is not None:
            campus = self._structure.get_campus(campus_id)
            if campus is None or campus.org_id != org_id:
                raise NotFoundError("Campus not found.")
            hit = self._profiles.lookup_code(campus_id, code)
            return hit.user_id if hit is not None else None
        for campus in self._structure.list_campuses(org_id):
            hit = self._profiles.lookup_code(campus.campus_id, code)
            if hit is not None:
                return hit.user_id
        return None

    def list_types(self) -> list[OrgType]:
        """Public org-kind catalog for filters and the create form."""
        return self._types.list_types()
