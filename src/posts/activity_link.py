"""A post may point at one activity of its organization, so readers can sign up from it."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.activities.queries import summary_query, to_summary
from src.activities.rules import COMPLETED, PUBLISHED
from src.activities.schemas import ActivitySummary
from src.models.activities import Activity
from src.validation import validation_failure

# A draft is only for managers and a cancelled activity has nothing to join, so a
# post can point only at an activity people can see. One that is cancelled later
# stays linked and shows its status.
LINKABLE_STATUSES = (PUBLISHED, COMPLETED)


def linkable(activity_org_id: uuid.UUID, status: str, post_org_id: uuid.UUID) -> bool:
    return activity_org_id == post_org_id and status in LINKABLE_STATUSES


def check_linkable(db: Session, org_id: uuid.UUID, activity_id: uuid.UUID) -> uuid.UUID:
    """The activity ID when the post may point at it, otherwise a 422."""
    activity = db.scalar(
        select(Activity).where(
            Activity.id == activity_id, Activity.deleted_at.is_(None)
        )
    )
    if activity is None or not linkable(activity.org_id, activity.status, org_id):
        raise validation_failure({"activity_id": "activity_not_linkable"})
    return activity.id


def activity_summaries(
    db: Session, activity_ids: set[uuid.UUID]
) -> dict[uuid.UUID, ActivitySummary]:
    """Summaries of live activities. A deleted activity is left out, so the post shows none."""
    if not activity_ids:
        return {}
    rows = db.execute(summary_query().where(Activity.id.in_(activity_ids))).all()
    return {summary.id: summary for summary in map(to_summary, rows)}
