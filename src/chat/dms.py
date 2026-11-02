"""Direct messages between two active members of one organization."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.chat.schemas import DmResponse
from src.models.auth import User
from src.models.chat import OrgDmPair
from src.models.organizations import Organization
from src.organizations.access import ACTIVE, get_access
from src.validation import validation_failure


def open_dm(
    db: Session, org: Organization, user_id: uuid.UUID, peer_id: uuid.UUID
) -> OrgDmPair:
    """Opening the same pair again returns the same room."""
    if peer_id == user_id:
        raise validation_failure({"user_id": "self_dm"})
    if get_access(db, org, peer_id).status != ACTIVE:
        raise validation_failure({"user_id": "not_a_member"})
    if get_access(db, org, user_id).status != ACTIVE:
        raise validation_failure({"user_id": "not_a_member"})
    low, high = sorted([user_id, peer_id])
    # ON CONFLICT covers both the pair key and the room key, so two requests cannot both insert.
    db.execute(
        insert(OrgDmPair)
        .values(org_id=org.id, user_lo=low, user_hi=high, room_id=uuid.uuid7())
        .on_conflict_do_nothing()
    )
    db.commit()
    pair = db.get(OrgDmPair, (org.id, low, high))
    assert pair is not None
    return pair


def list_dms(db: Session, org: Organization, user_id: uuid.UUID) -> list[DmResponse]:
    pairs = db.scalars(
        select(OrgDmPair).where(
            OrgDmPair.org_id == org.id,
            or_(OrgDmPair.user_lo == user_id, OrgDmPair.user_hi == user_id),
        )
    ).all()
    peer_ids = {
        pair.user_hi if pair.user_lo == user_id else pair.user_lo for pair in pairs
    }
    names = dict(
        db.execute(select(User.id, User.full_name).where(User.id.in_(peer_ids))).all()
    )
    return [
        DmResponse(
            room_id=pair.room_id,
            peer_id=peer,
            peer_name=names.get(peer, ""),
        )
        for pair in pairs
        for peer in [pair.user_hi if pair.user_lo == user_id else pair.user_lo]
    ]


def dm_response(db: Session, pair: OrgDmPair, user_id: uuid.UUID) -> DmResponse:
    peer = pair.user_hi if pair.user_lo == user_id else pair.user_lo
    name = db.scalar(select(User.full_name).where(User.id == peer)) or ""
    return DmResponse(room_id=pair.room_id, peer_id=peer, peer_name=name)
