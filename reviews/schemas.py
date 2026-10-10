"""Request/response DTOs for the reviews API surface."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewCreateBody(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class ReviewResponse(BaseModel):
    review_id: UUID
    activity_id: UUID
    student_id: UUID
    student_name: str
    rating: int
    comment: str | None
    created_at: datetime


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    average_rating: float | None
    count: int
    can_review: bool
