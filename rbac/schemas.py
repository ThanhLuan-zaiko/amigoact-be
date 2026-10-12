"""Pydantic DTOs for org-scoped role management."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from rbac.roles_service import DESCRIPTION_MAX, NAME_MAX, NAME_MIN


class CreateRoleRequest(BaseModel):
    """New custom role: display name plus a non-empty permission set."""

    name: str = Field(min_length=NAME_MIN, max_length=NAME_MAX)
    description: str = Field(default="", max_length=DESCRIPTION_MAX)
    permissions: list[str] = Field(min_length=1, max_length=32)


class UpdateRoleRequest(BaseModel):
    """Partial role edit; at least one field is required."""

    name: str | None = Field(default=None, min_length=NAME_MIN, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    permissions: list[str] | None = Field(
        default=None, min_length=1, max_length=32
    )

    @model_validator(mode="after")
    def _require_field(self) -> UpdateRoleRequest:
        if (
            self.name is None
            and self.description is None
            and self.permissions is None
        ):
            raise ValueError("At least one field must be provided.")
        return self


class OrgRoleResponse(BaseModel):
    """One role row for the org role list/editor."""

    id: UUID
    name: str
    description: str
    permissions: list[str]
    member_count: int
    is_system: bool


class OrgRoleListResponse(BaseModel):
    """Role list plus the permission catalog clients may assign."""

    items: list[OrgRoleResponse]
    assignable_permissions: list[str]
