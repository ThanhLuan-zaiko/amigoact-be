"""Claim activity tags into the author's book, then the org catalog."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class PersonalTagBook(Protocol):
    """The slice of the personal catalog an activity save needs."""

    def ensure(self, user_id: UUID, names: list[str] | None) -> list[str]:
        """Claim missing names and return this user's spelling."""

    def bind_activity(
        self,
        user_id: UUID,
        org_id: UUID,
        activity_id: UUID,
        names: list[str] | None,
    ) -> None:
        """Remember which of the user's tags this activity carries."""


class OrgTagClaims(Protocol):
    """Org catalog claim used after the personal book accepts the names."""

    def ensure(self, org_id: UUID, names: list[str] | None) -> list[str]:
        """Resolve names to the org's canonical spelling."""


def claim_activity_tags(
    org_tags: OrgTagClaims,
    user_tags: PersonalTagBook | None,
    org_id: UUID,
    actor_id: UUID,
    names: list[str] | None,
) -> list[str]:
    """Personal spelling first, then the org catalog, same as a post save."""
    claimed = names
    if user_tags is not None:
        claimed = user_tags.ensure(actor_id, claimed)
    return org_tags.ensure(org_id, claimed)


def bind_activity_tags(
    user_tags: PersonalTagBook | None,
    actor_id: UUID,
    org_id: UUID,
    activity_id: UUID,
    names: list[str] | None,
) -> None:
    """Record the activity on the author's tags. No-op without a book."""
    if user_tags is None:
        return
    user_tags.bind_activity(actor_id, org_id, activity_id, names)
