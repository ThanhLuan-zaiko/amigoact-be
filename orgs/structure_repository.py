"""cqlengine persistence for campuses and departments."""

from __future__ import annotations

from uuid import UUID

from core.security import utcnow
from orgs.model import (
    Campus,
    OrgType,
    CampusByOrg,
    Department,
    DepartmentByCampus,
    DepartmentByOrg,
)
from orgs.structure_interfaces import OrgTypeStore, StructureStore


class CqlStructureStore(StructureStore):
    """Canonical rows plus the org/campus feed mirrors."""

    def create_campus(
        self,
        campus_id: UUID,
        org_id: UUID,
        name: str,
        address: str | None,
    ) -> Campus:
        row = Campus.create(
            id=campus_id,
            org_id=org_id,
            name=name,
            address=address,
            status="active",
            created_at=utcnow(),
        )
        CampusByOrg.create(org_id=org_id, campus_id=campus_id, name=name)
        return row

    def get_campus(self, campus_id: UUID) -> Campus | None:
        try:
            return Campus.objects(id=campus_id).get()
        except Campus.DoesNotExist:
            return None

    def list_campuses(self, org_id: UUID) -> list[CampusByOrg]:
        return list(CampusByOrg.objects(org_id=org_id).all())

    def update_campus(
        self,
        campus_id: UUID,
        name: str,
        address: str | None,
        status: str,
    ) -> Campus | None:
        row = self.get_campus(campus_id)
        if row is None:
            return None
        row.update(name=name, address=address, status=status)
        CampusByOrg.objects(
            org_id=row.org_id, campus_id=campus_id
        ).update(name=name)
        return self.get_campus(campus_id)

    def create_department(
        self,
        department_id: UUID,
        org_id: UUID,
        campus_id: UUID | None,
        name: str,
        code: str | None,
    ) -> Department:
        row = Department.create(
            id=department_id,
            org_id=org_id,
            campus_id=campus_id,
            name=name,
            code=code,
            status="active",
            created_at=utcnow(),
        )
        DepartmentByOrg.create(
            org_id=org_id,
            department_id=department_id,
            name=name,
            code=code,
            campus_id=campus_id,
        )
        if campus_id is not None:
            DepartmentByCampus.create(
                campus_id=campus_id,
                department_id=department_id,
                name=name,
                code=code,
            )
        return row

    def get_department(self, department_id: UUID) -> Department | None:
        try:
            return Department.objects(id=department_id).get()
        except Department.DoesNotExist:
            return None

    def list_departments(self, org_id: UUID) -> list[DepartmentByOrg]:
        return list(DepartmentByOrg.objects(org_id=org_id).all())

    def update_department(
        self,
        department_id: UUID,
        campus_id: UUID | None,
        name: str,
        code: str | None,
        status: str,
    ) -> Department | None:
        row = self.get_department(department_id)
        if row is None:
            return None
        old_campus = row.campus_id
        row.update(
            campus_id=campus_id, name=name, code=code, status=status
        )
        DepartmentByOrg.objects(
            org_id=row.org_id, department_id=department_id
        ).update(name=name, code=code, campus_id=campus_id)
        if old_campus is not None and old_campus != campus_id:
            DepartmentByCampus.objects(
                campus_id=old_campus, department_id=department_id
            ).delete()
        if campus_id is not None:
            DepartmentByCampus.create(
                campus_id=campus_id,
                department_id=department_id,
                name=name,
                code=code,
            )
        return self.get_department(department_id)


class CqlOrgTypeStore(OrgTypeStore):
    def list_types(self) -> list[OrgType]:
        rows = list(OrgType.objects().all())
        return sorted(rows, key=lambda r: (r.sort_order or 0, r.code))
