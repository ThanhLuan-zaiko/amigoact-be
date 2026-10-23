"""Suggestions copied from other orgs the caller owns.

Selecting a name later claims a fresh catalog row in the current org.
Rename and delete stay independent after that copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import OrgTagStore
from core.exceptions import ForbiddenError, NotFoundError
from orgs.interfaces import OrgRepository

_LIMIT = 200


@dataclass(frozen=True)
class OwnedTagSuggestion:
    """One live tag the caller can copy into the org they are editing."""

    name: str
    slug: str
    org_id: UUID
    org_name: str


class OwnedTagService:
    """Live tags from the caller's other owned orgs."""

    def __init__(self, tags: OrgTagStore, orgs: OrgRepository) -> None:
        self._tags = tags
        self._orgs = orgs

    def list_owned(
        self, org_id: UUID, user_id: UUID
    ) -> list[OwnedTagSuggestion]:
        """Members of this org see tags from other orgs they own.

        A slug already present here, including one sitting in the trash,
        is omitted so the picker cannot offer a name the save would
        reject or rewrite.
        """
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if (
            getattr(org, "owner_id", None) != user_id
            and not self._orgs.is_member(org_id, user_id)
        ):
            raise ForbiddenError("Only org members can list tags.")
        blocked = {row.slug for row in self._tags.list(org_id)}
        seen: set[tuple[str, str]] = set()
        items: list[OwnedTagSuggestion] = []
        owned = [
            other
            for other in self._orgs.list_by_user(user_id)
            if other.id != org_id
            and getattr(other, "owner_id", None) == user_id
            and getattr(other, "deleted_at", None) is None
            and (getattr(other, "status", "active") or "active") == "active"
        ]
        owned.sort(key=lambda row: (row.name or "").casefold())
        for other in owned:
            rows = [
                row
                for row in self._tags.list(other.id)
                if row.deleted_at is None and row.slug not in blocked
            ]
            rows.sort(key=lambda row: row.name.casefold())
            for row in rows:
                key = (row.slug, row.name)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    OwnedTagSuggestion(
                        name=row.name,
                        slug=row.slug,
                        org_id=other.id,
                        org_name=other.name,
                    )
                )
                if len(items) >= _LIMIT:
                    return items
        return items
