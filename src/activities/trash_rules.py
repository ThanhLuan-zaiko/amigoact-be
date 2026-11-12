"""Rules for the activity trash. Pure functions, so they need no database."""

from datetime import datetime, timedelta

from src.organizations.access import ACTIVE, Access

# A deleted draft stays in the trash this long, then it is removed for good.
TRASH_DAYS = 30


def purge_at(deleted_at: datetime) -> datetime:
    """When an activity in the trash is removed for good."""
    return deleted_at + timedelta(days=TRASH_DAYS)


def trash_expired(deleted_at: datetime, now: datetime) -> bool:
    return purge_at(deleted_at) <= now


def may_restore(access: Access) -> bool:
    """Owners and admins see the trash and bring activities back."""
    return access.status == ACTIVE and access.can_manage


def may_purge(access: Access) -> bool:
    """Only the owner removes an activity for good, because it cannot be undone."""
    return access.status == ACTIVE and access.role == "owner"
