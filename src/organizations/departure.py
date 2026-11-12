"""What happens around a member who leaves or is removed, besides the row change."""

import uuid

from sqlalchemy.orm import Session

from src.models.auth import User
from src.models.organizations import Organization
from src.notifications.events import notify, organization_data
from src.organizations import signals
from src.organizations.access import admin_user_ids


def member_gone(
    db: Session, org: Organization, user_id: uuid.UUID, *, removed: bool
) -> None:
    """Cut the person's live topics, update open pages, and tell who needs to know.

    Call after the roles are cleared, so a leaving admin is not told about themself.
    """
    signals.lose_membership(db, org.id, user_id)
    signals.members_changed(db, org.id)
    signals.membership_changed(db, org.id, user_id)
    if removed:
        notify(db, user_id, "membership_removed", organization_data(org))
        return
    member = db.get(User, user_id)
    data = {
        **organization_data(org),
        "organization_id": str(org.id),
        "member_id": str(user_id),
        "member_name": member.full_name if member else None,
    }
    managers = {org.owner_id, *admin_user_ids(db, org.id)} - {user_id}
    for manager_id in sorted(managers):
        notify(db, manager_id, "member_left", data)
