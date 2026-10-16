"""StructureService (campuses + departments) unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
import uuid_utils

from core.exceptions import ForbiddenError, NotFoundError
from orgs.structure_interfaces import StructureStore
from orgs.structure_service import StructureService
from tests.unit.member_fakes import FakeAccess
from tests.unit.org_fakes import FakeOrgs
from tests.unit.profile_fakes import FakeProfiles


class FakeTypes:
    def __init__(self) -> None:
        from types import SimpleNamespace

        self.rows = [
            SimpleNamespace(code="club", name="CLB", sort_order=0)
        ]

    def list_types(self):
        return self.rows


class FakeStructure(StructureStore):
    def __init__(self) -> None:
        from types import SimpleNamespace

        self.campuses: dict = {}
        self.departments: dict = {}
        self._ns = SimpleNamespace

    def create_campus(self, campus_id, org_id, name, address):
        row = self._ns(
            id=campus_id, org_id=org_id, name=name, address=address,
            status="active", created_at=datetime.now(UTC),
            campus_id=campus_id,
        )
        self.campuses[campus_id] = row
        return row

    def get_campus(self, campus_id):
        return self.campuses.get(campus_id)

    def list_campuses(self, org_id):
        return [c for c in self.campuses.values() if c.org_id == org_id]

    def update_campus(self, campus_id, name, address, status):
        row = self.campuses.get(campus_id)
        if row is None:
            return None
        row.name, row.address, row.status = name, address, status
        return row

    def create_department(self, department_id, org_id, campus_id, name, code):
        row = self._ns(
            id=department_id, org_id=org_id, campus_id=campus_id,
            name=name, code=code, status="active",
            created_at=datetime.now(UTC), department_id=department_id,
        )
        self.departments[department_id] = row
        return row

    def get_department(self, department_id):
        return self.departments.get(department_id)

    def list_departments(self, org_id):
        return [d for d in self.departments.values() if d.org_id == org_id]

    def update_department(self, department_id, campus_id, name, code, status):
        row = self.departments.get(department_id)
        if row is None:
            return None
        row.campus_id, row.name, row.code, row.status = (
            campus_id, name, code, status,
        )
        return row


def _svc():
    orgs, structure, access = FakeOrgs(), FakeStructure(), FakeAccess()
    profiles = FakeProfiles()
    return (
        StructureService(
            orgs=orgs, structure=structure, access=access,
            profiles=profiles, types=FakeTypes(),
        ),
        orgs, structure, profiles,
    )


def _org(orgs: FakeOrgs, owner: UUID):
    return orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )


def _member(orgs: FakeOrgs, org_id, user_id) -> None:
    orgs.members.setdefault(org_id, set()).add(user_id)


def test_owner_manages_campus_tree():
    service, orgs, structure, _profiles = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org(orgs, owner)
    _member(orgs, org.id, member)

    campus = service.create_campus(org.id, owner, "C\u01a1 s\u1edf 1", "H\xe0 N\u1ed9i")
    dept = service.create_department(
        org.id, owner, "CNTT", "IT", campus.id
    )
    assert dept.campus_id == campus.id

    rows = service.list_campuses(org.id, member)
    assert [r.name for r in rows] == ["C\u01a1 s\u1edf 1"]
    depts = service.list_departments(org.id, member)
    assert [d.name for d in depts] == ["CNTT"]

    updated = service.update_campus(
        org.id, campus.id, owner, "C\u01a1 s\u1edf 2", None, None
    )
    assert updated.name == "C\u01a1 s\u1edf 2"


def test_non_member_cannot_read_structure():
    service, orgs, *_ = _svc()
    owner, stranger = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org(orgs, owner)
    with pytest.raises(ForbiddenError):
        service.list_campuses(org.id, stranger)


def test_member_cannot_write_structure():
    service, orgs, *_ = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org(orgs, owner)
    _member(orgs, org.id, member)
    with pytest.raises(ForbiddenError):
        service.create_campus(org.id, member, "X", None)


def test_department_campus_must_belong_to_org():
    service, orgs, *_ = _svc()
    owner = uuid_utils.uuid7()
    org1, org2 = _org(orgs, owner), orgs.create(
        uuid_utils.uuid7(), owner, "Club 2", "club-2", "", "club-2",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )
    foreign = service.create_campus(org2.id, owner, "Kh\xe1c", None)
    with pytest.raises(NotFoundError):
        service.create_department(org1.id, owner, "Khoa", None, foreign.id)


def test_lookup_student_by_code_across_campuses():
    service, orgs, structure, profiles = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    campus = service.create_campus(org.id, owner, "CS1", None)
    student = uuid_utils.uuid7()
    profiles.upsert_profile(
        student, "SV123", campus.id, None, "CTK43", 2022,
        "BK", None, set(), "studying", datetime.now(UTC),
    )
    hit = service.lookup_student(org.id, owner, " SV123 ", campus.id)
    assert hit == student
    hit2 = service.lookup_student(org.id, owner, "SV123", None)
    assert hit2 == student
    assert service.lookup_student(org.id, owner, "ZZZ", None) is None
