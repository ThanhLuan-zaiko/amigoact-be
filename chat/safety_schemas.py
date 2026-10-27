"""Pydantic DTOs for chat safety (attachment policy, timeouts)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TimeoutResponse(BaseModel):
    user_id: UUID
    user_name: str
    until: datetime
    set_by: UUID
    reason: str


class SafetyResponse(BaseModel):
    attach_restricted: bool
    my_timeout_until: datetime | None = None
    timeouts: list[TimeoutResponse] = []


class AttachPolicyRequest(BaseModel):
    restricted: bool


class AttachPolicyResponse(BaseModel):
    attach_restricted: bool


class TimeoutRequest(BaseModel):
    minutes: int = Field(ge=1, le=10_080)
    reason: str = Field(default="", max_length=200)
