"""Publishing a draft activity."""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.orm import Session

from src.activities.rules import (
    DRAFT,
    PUBLISHED,
    completeness_errors,
    publish_errors,
)
from src.auth.errors import api_error
from src.models.activities import Activity
from src.organizations.deletion import lock_live_organization
from src.validation import validation_failure


def publish_activity(db: Session, activity: Activity) -> None:
    if activity.status != DRAFT:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_editable")
    # The same lock a soft delete takes, so an activity cannot open in an organization
    # that is being deleted.
    if not lock_live_organization(db, activity.org_id):
        raise api_error(status.HTTP_404_NOT_FOUND, "organization_not_found")

    errors = publish_errors(
        start_at=activity.start_at,
        end_at=activity.end_at,
        deadline=activity.registration_deadline,
        location=activity.location,
        is_remote=activity.is_remote,
        now=datetime.now(UTC),
    )

    errors.update(
        completeness_errors(
            description=activity.description,
            city=activity.city,
            hours_awarded=activity.hours_awarded,
        )
    )

    if errors:
        raise validation_failure(errors)
    activity.status = PUBLISHED
    activity.published_at = datetime.now(UTC)
    db.commit()
