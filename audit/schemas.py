"""Pydantic DTOs for the org audit feed."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    log_id: UUID
    occurred_at: datetime
    actor_id: UUID
    actor_name: str
    action: str
    resource_type: str
    resource_id: UUID | None
    result: str


class AuditFeedResponse(BaseModel):
    items: list[AuditEntryResponse]
