"""HTTP surface for activity reviews (thin router)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_optional_user,
)
from core.dependencies_features import get_review_service
from reviews.schemas import (
    ReviewCreateBody,
    ReviewListResponse,
    ReviewResponse,
)
from reviews.service import ReviewView

if TYPE_CHECKING:
    from reviews.service import ReviewService

router = APIRouter(tags=["reviews"])


def _out(view: ReviewView) -> ReviewResponse:
    return ReviewResponse(
        review_id=view.review_id,
        activity_id=view.activity_id,
        student_id=view.student_id,
        student_name=view.student_name,
        rating=view.rating,
        comment=view.comment,
        created_at=view.created_at,
    )


@router.post(
    "/activities/{activity_id}/reviews",
    response_model=ReviewResponse,
    status_code=201,
)
def create_review(
    activity_id: UUID,
    body: ReviewCreateBody,
    current: CurrentUser = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
) -> ReviewResponse:
    """An attended volunteer rates the activity, once."""
    return _out(
        service.create(
            activity_id, current.id, body.rating, body.comment
        )
    )


@router.get(
    "/activities/{activity_id}/reviews",
    response_model=ReviewListResponse,
)
def list_reviews(
    activity_id: UUID,
    current: CurrentUser | None = Depends(get_optional_user),
    service: ReviewService = Depends(get_review_service),
) -> ReviewListResponse:
    """Public review feed with the caller's eligibility flag."""
    items = service.list_for_activity(activity_id)
    ratings = [row.rating for row in items if row.rating]
    return ReviewListResponse(
        items=[_out(view) for view in items],
        average_rating=(
            round(sum(ratings) / len(ratings), 1) if ratings else None
        ),
        count=len(items),
        can_review=(
            service.can_review(activity_id, current.id)
            if current is not None
            else False
        ),
    )
