"""DTOs for the cross-org activity feed behind /manage/events."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from activities.schemas import ActivitySummary


class MyActivityOrg(BaseModel):
    """An org the caller belongs to, with what they may do in it."""

    id: UUID
    name: str
    slug: str
    kind: str
    can_create: bool
    can_manage: bool
    activity_count: int
    # Public logo path (/media/...) or null; the rail falls back to initials.
    logo_url: str | None = None


class MyActivityItem(ActivitySummary):
    """Feed row: the org-scoped summary plus the caller's manage right."""

    can_manage: bool = False


class MyActivitiesResponse(BaseModel):
    items: list[MyActivityItem]
    orgs: list[MyActivityOrg]
