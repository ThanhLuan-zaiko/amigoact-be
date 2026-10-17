"""Pydantic DTOs for org memberships (validation lives here)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from orgs.schemas import BucketCount

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MemberStatus = Literal["active", "invited", "suspended", "left", "revoked"]
MemberSort = Literal["newest", "name", "role"]
JoinPolicy = Literal["invite", "open"]


def validate_member_email(value: str) -> str:
    """Invite email shape check, normalized to lowercase."""
    address = value.strip().lower()
    if len(address) > 254 or not _EMAIL_PATTERN.match(address):
        raise ValueError("Email address is invalid.")
    return address


class InviteMemberRequest(BaseModel):
    """Manager invites an account by email, optionally with a role."""

    email: str
    role: str = Field(default="member", min_length=1, max_length=40)

    _email = field_validator("email", mode="before")(validate_member_email)  # noqa: SLF001


class UpdateMemberRequest(BaseModel):
    """Role set replace, legacy role grant, or status change."""

    role: Literal["member", "admin"] | None = None
    roles: list[str] | None = Field(default=None, max_length=20)
    status: Literal["suspended", "active"] | None = None

    @model_validator(mode="after")
    def _require_field(self) -> UpdateMemberRequest:
        if self.role is not None and self.roles is not None:
            raise ValueError("Provide either role or roles, not both.")
        if self.role is None and self.roles is None and self.status is None:
            raise ValueError("Either role, roles or status must be provided.")
        return self


class SkillMatchResponse(BaseModel):
    """Coordinator matching row: member name plus self-declared level."""

    user_id: UUID
    full_name: str
    level: int


class MemberResponse(BaseModel):
    """One roster row; email only reaches roster-managing viewers."""

    user_id: UUID
    org_id: UUID
    full_name: str
    avatar_url: str | None = None
    email: str | None = None
    roles: list[str] = []
    status: MemberStatus
    invited_by: UUID | None = None
    invited_by_name: str | None = None
    joined_at: datetime


class MemberListPage(BaseModel):
    """One roster page plus facets and the caller's capabilities."""

    items: list[MemberResponse]
    total: int
    counts: list[BucketCount] = []
    viewer_role: str = "member"
    viewer_permissions: list[str] = []


class MyMembership(BaseModel):
    """One membership link of the caller, with org display fields."""

    org_id: UUID
    org_name: str
    org_slug: str
    roles: list[str] = []
    status: MemberStatus
    invited_by_name: str | None = None
    joined_at: datetime


class MembershipPage(BaseModel):
    """The caller's memberships/invitations across orgs."""

    items: list[MyMembership]
    total: int
