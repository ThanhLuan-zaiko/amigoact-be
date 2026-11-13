"""Request and response bodies of the role API."""

import uuid
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

from src.organizations.permissions import CATALOG
from src.validation import Uuid7, has_letter, single_line

MAX_ROLES = 25
MAX_ROLES_PER_MEMBER = 10

RoleName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
    AfterValidator(single_line),
    AfterValidator(has_letter),
]
# "" is the default colour. Anything else must be exactly "#rrggbb".
RoleColor = Annotated[
    str, Field(max_length=7, pattern=r"^(#[0-9a-fA-F]{6})?$"), AfterValidator(str.lower)
]
PermissionCode = Literal[
    "administrator",
    "organization.update",
    "roles.create",
    "roles.update",
    "roles.delete",
    "roles.assign",
    "members.remove",
    "applications.review",
    "activities.create",
    "activities.update",
    "activities.delete",
    "activities.registrations",
    "attendance.checkin",
    "attendance.hours",
    "attendance.appeals",
    "certificates.templates",
    "certificates.issue",
    "posts.announce",
    "posts.pin",
    "posts.moderate",
    "channels.create",
    "channels.manage",
    "channels.read_restricted",
]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _no_duplicates(values: list[object]) -> None:
    if len(values) != len(set(values)):
        raise PydanticCustomError("duplicate_items", "Items must be unique")


class RoleCreateRequest(StrictBody):
    name: RoleName
    color: RoleColor = ""
    permissions: list[PermissionCode] = Field(default_factory=list, max_length=30)

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: list[str]) -> list[str]:
        _no_duplicates(list(value))
        return value


class RoleUpdateRequest(StrictBody):
    name: RoleName | None = None
    color: RoleColor | None = None
    permissions: list[PermissionCode] | None = Field(default=None, max_length=30)

    @field_validator("name", "color", "permissions")
    @classmethod
    def not_null(cls, value: object) -> object:
        if value is None:
            raise PydanticCustomError("required", "Send a value or leave the field out")
        return value

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: list[str] | None) -> list[str] | None:
        _no_duplicates(list(value or []))
        return value


class RoleOrderRequest(StrictBody):
    """Role ids from the highest to the lowest, for the roles the caller may move."""

    role_ids: list[Uuid7] = Field(min_length=1, max_length=MAX_ROLES)

    @field_validator("role_ids")
    @classmethod
    def unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        _no_duplicates(list(value))
        return value


class MemberRolesRequest(StrictBody):
    """The full set of roles the member should hold. An empty list removes them all."""

    role_ids: list[Uuid7] = Field(max_length=MAX_ROLES_PER_MEMBER)

    @field_validator("role_ids")
    @classmethod
    def unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        _no_duplicates(list(value))
        return value


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    color: str
    position: int
    permissions: list[str]
    member_count: int
    # True when the role sits below the caller's top role.
    below_you: bool


class RoleList(BaseModel):
    items: list[RoleResponse]
    # Every permission code, so the interface lists the ones this build knows.
    catalog: list[str] = Field(default_factory=lambda: list(CATALOG))


class MemberRoleBadge(BaseModel):
    id: uuid.UUID
    name: str
    color: str
