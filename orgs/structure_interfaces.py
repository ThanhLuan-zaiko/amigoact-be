"""Ports for the org campus/department structure."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from orgs.model import (
    Campus,
    CampusByOrg,
    Department,
    DepartmentByOrg,
    OrgType,
)


class StructureStore(ABC):
    """Persistence port for campuses and departments plus their feeds."""

    @abstractmethod
    def create_campus(
        self,
        campus_id: UUID,
        org_id: UUID,
        name: str,
        address: str | None,
    ) -> Campus:
        """Insert the campus row and its by-org feed row."""

    @abstractmethod
    def get_campus(self, campus_id: UUID) -> Campus | None:
        """Load one campus by primary key."""

    @abstractmethod
    def list_campuses(self, org_id: UUID) -> list[CampusByOrg]:
        """Campus feed rows of one org."""

    @abstractmethod
    def update_campus(
        self,
        campus_id: UUID,
        name: str,
        address: str | None,
        status: str,
    ) -> Campus | None:
        """Patch one campus and mirror the feed name."""

    @abstractmethod
    def create_department(
        self,
        department_id: UUID,
        org_id: UUID,
        campus_id: UUID | None,
        name: str,
        code: str | None,
    ) -> Department:
        """Insert the department row plus campus/org feed rows."""

    @abstractmethod
    def get_department(self, department_id: UUID) -> Department | None:
        """Load one department by primary key."""

    @abstractmethod
    def list_departments(self, org_id: UUID) -> list[DepartmentByOrg]:
        """Department feed rows of one org across campuses."""

    @abstractmethod
    def update_department(
        self,
        department_id: UUID,
        campus_id: UUID | None,
        name: str,
        code: str | None,
        status: str,
    ) -> Department | None:
        """Patch one department and mirror both feed rows."""


class OrgTypeStore(ABC):
    """Persistence port for the org-kind lookup table."""

    @abstractmethod
    def list_types(self) -> list[OrgType]:
        """Every kind ordered by sort_order."""
