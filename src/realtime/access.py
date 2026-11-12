"""The one rule per topic kind that decides who may listen.

It runs on every subscribe, so a topic someone cannot read looks the same as
one that does not exist. Losing access mid-connection goes through bus.revoke.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.chat.rooms import readable_by
from src.models.organizations import Organization
from src.organizations.access import get_access
from src.organizations.service import live_organization
from src.realtime.names import ORG, ROOM, USER, parse_topic


def can_listen(db: Session, topic: str, user_id: uuid.UUID) -> bool:
    parsed = parse_topic(topic)
    if parsed is None:
        return False
    kind, target = parsed
    if kind == USER:
        return target == user_id
    if kind == ROOM:
        return readable_by(db, target, user_id)
    org = db.scalar(
        select(Organization).where(Organization.id == target, *live_organization())
    )
    if org is None:
        return False
    access = get_access(db, org, user_id)
    if kind == ORG:
        return access.role is not None
    return access.can_manage
