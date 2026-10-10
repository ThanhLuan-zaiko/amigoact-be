"""Pydantic DTOs for org memberships (validation lives here)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from orgs.schemas import BucketCount

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MemberRole = Literal["owner", "admin", "member"]
MemberStatus = Literal["active", "invited", "suspended", "left"]
MemberSort = Literal["newest", "name", "role"]
JoinPolicy = Literal["invite", "open"]


def validate_member_email(value: str) -> str:
    """Invite email shape check, normalized to lowercase."""
    address = value.strip().lower()
    if len(address) > 254 or not _EMAIL_PATTERN.match(address):
        raise ValueError("Email address is invalid.")
    return address


class InviteMemberRequest(BaseModel):
    """Manager invites an account by email, optionally as admin."""

    email: str
    role: Literal["member", "admin"] = "member"

    _email = field_validator("email", mode="before")(validate_member_email)  # noqa: SLF001


class UpdateMemberRequest(BaseModel):
    """Role grant (owner) or status change (owner/admin); one required."""

    role: Literal["member", "admin"] | None = None
    status: Literal["suspended", "active"] | None = None

    @model_validator(mode="after")
    def _require_field(self) -> UpdateMemberRequest:
        if self.role is None and self.status is None:
            raise ValueError("Either role or status must be provided.")
        return self


class MemberResponse(BaseModel):
    """One roster row; email only reaches owner/admin viewers."""

    user_id: UUID
    org_id: UUID
    full_name: str
    email: str | None = None
    role: MemberRole
    status: MemberStatus
    joined_at: datetime


class MemberListPage(BaseModel):
    """One roster page plus facets and the caller's effective role."""

    items: list[MemberResponse]
    total: int
    counts: list[BucketCount] = []
    viewer_role: MemberRole = "member"


class MyMembership(BaseModel):
    """One membership link of the caller, with org display fields."""

    org_id: UUID
    org_name: str
    org_slug: str
    role: MemberRole
    status: MemberStatus
    joined_at: datetime


class MembershipPage(BaseModel):
    """The caller's memberships/invitations across orgs."""

    items: list[MyMembership]
    total: int
