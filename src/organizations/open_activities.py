"""Activities of an organization that are still open, for the detail and the delete check."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.activities.rules import PUBLISHED
from src.models.activities import Activity


def open_activity_count(db: Session, org_id: uuid.UUID) -> int:
    """A published activity is open until it is completed or cancelled."""
    count = db.scalar(
        select(func.count())
        .select_from(Activity)
        .where(Activity.org_id == org_id, Activity.status == PUBLISHED)
    )
    return count or 0
