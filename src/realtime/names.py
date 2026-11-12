"""Topic names. Pure, so any module can import them without a cycle."""

import uuid

USER = "user"
ORG = "org"
MANAGERS = "org-managers"
ROOM = "room"
KINDS = (USER, ORG, MANAGERS, ROOM)


def user_topic(user_id: uuid.UUID) -> str:
    """Every socket of one person. It is joined on connect, never by subscribing."""
    return f"{USER}:{user_id}"


def org_topic(org_id: uuid.UUID) -> str:
    """Active members of an organization: the member list and what they all see."""
    return f"{ORG}:{org_id}"


def managers_topic(org_id: uuid.UUID) -> str:
    """The owner and admins: applications and other review work."""
    return f"{MANAGERS}:{org_id}"


def room_topic(room_id: uuid.UUID) -> str:
    """A chat room: the organization room, a channel, or a direct message."""
    return f"{ROOM}:{room_id}"


def parse_topic(topic: object) -> tuple[str, uuid.UUID] | None:
    if not isinstance(topic, str) or len(topic) > 64:
        return None
    kind, _, raw_id = topic.partition(":")
    if kind not in KINDS:
        return None
    try:
        return kind, uuid.UUID(raw_id)
    except ValueError:
        return None
