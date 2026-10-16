"""Request/response DTOs for the API key endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    """Issue body: display name plus optional scope list and TTL."""

    name: str = Field(min_length=2, max_length=80)
    scopes: set[str] = Field(default_factory=set)
    ttl_days: int | None = Field(default=None, ge=1, le=365)


class ApiKeyIssuedResponse(BaseModel):
    """Returned once; carries the plaintext secret."""

    key_id: UUID
    name: str
    api_key: str
    scopes: set[str]
    expires_at: datetime | None = None


class ApiKeyItem(BaseModel):
    """Listing row; secret material never leaves the server."""

    key_id: UUID
    name: str
    scopes: set[str]
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None
