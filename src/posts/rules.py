"""Rules for the organization feed: who may post, what each kind means, and the limits."""

import re
import unicodedata
from datetime import datetime, timedelta

from src.organizations.access import ACTIVE, Access

ANNOUNCEMENT = "announcement"
DISCUSSION = "discussion"
PUBLIC = "public"
MEMBERS = "members"
POST_ACTIVE = "active"
POST_DRAFT = "draft"
TAG_LIMIT = 3
TAG_NAME_MAX = 40
MEDIA_LIMIT = 10
POST_CREATE_LIMIT = 30
POST_WINDOW = 60 * 60
COMMENT_LIMIT = 120
TRENDING_DAYS = 30
TRENDING_LIMIT = 10
# A deleted post stays in the trash this long, then it is removed for good.
TRASH_DAYS = 30
# The author may fix a comment for this long after writing it.
COMMENT_EDIT_MINUTES = 15
# NFKD does not split the Vietnamese letter d with stroke, so it is mapped by hand.
_STROKED_D = str.maketrans({"\u0111": "d", "\u0110": "D"})
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def default_visibility(kind: str) -> str:
    """Announcements are for everyone, discussions are for members unless chosen otherwise."""
    return PUBLIC if kind == ANNOUNCEMENT else MEMBERS


def may_post(kind: str, access: Access) -> bool:
    """Any active member can start a discussion. Only managers can announce."""
    if access.status != ACTIVE:
        return False
    return kind == DISCUSSION or access.can_manage


def tag_slug(name: str) -> str | None:
    """Lowercase ASCII words joined by hyphens, or None when no letter or digit is left."""
    decomposed = unicodedata.normalize("NFKD", name.translate(_STROKED_D))
    ascii_name = decomposed.encode("ascii", "ignore").decode().lower()
    slug = _NOT_SLUG.sub("-", ascii_name).strip("-")[:TAG_NAME_MAX].strip("-")
    return slug or None


def purge_at(deleted_at: datetime) -> datetime:
    """When a post in the trash is removed for good."""
    return deleted_at + timedelta(days=TRASH_DAYS)


def trash_expired(deleted_at: datetime, now: datetime) -> bool:
    return purge_at(deleted_at) <= now


def comment_editable(created_at: datetime, now: datetime) -> bool:
    """A comment can be edited only shortly after it was written."""
    return now - created_at < timedelta(minutes=COMMENT_EDIT_MINUTES)


def may_restore(access: Access) -> bool:
    """Owners and admins bring posts and comments back from the trash."""
    return access.status == ACTIVE and access.can_manage


def may_purge(access: Access) -> bool:
    """Only the owner removes a post for good, because it cannot be undone."""
    return access.status == ACTIVE and access.role == "owner"
