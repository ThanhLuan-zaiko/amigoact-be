"""cqlengine persistence for the personal tag catalog."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from activities.user_tag_model import (
    UserActivityTag,
    UserActivityTagSet,
    UserPostTag,
    UserPostTagSet,
    UserTag,
)


class CqlUserTagStore:
    """tags_by_user rows plus the post edges that feed the tags rail."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def list_tags(self, user_id: UUID) -> list[UserTag]:
        return list(UserTag.objects(user_id=user_id).all())

    def get(self, user_id: UUID, slug: str) -> UserTag | None:
        return UserTag.objects(user_id=user_id, slug=slug).first()

    def insert(
        self, user_id: UUID, slug: str, name: str, now: datetime
    ) -> bool:
        """True when this call created the row."""
        applied = get_session().execute(
            f"INSERT INTO {self._keyspace}.tags_by_user"
            " (user_id, slug, name, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s) IF NOT EXISTS",
            [user_id, slug, name, now, now],
        )
        return bool(applied.was_applied)

    def update_name(
        self, user_id: UUID, slug: str, name: str, now: datetime
    ) -> None:
        UserTag.objects(user_id=user_id, slug=slug).update(
            name=name, updated_at=now
        )

    def delete_tag(self, user_id: UUID, slug: str) -> None:
        UserTag.objects(user_id=user_id, slug=slug).delete()

    def posts_for(self, user_id: UUID, slug: str) -> list[UserPostTag]:
        return list(
            UserPostTag.objects(user_id=user_id, tag_slug=slug).limit(40)
        )

    def orgs_for(self, user_id: UUID, slug: str) -> set[UUID]:
        return {row.org_id for row in self.posts_for(user_id, slug)}

    def slugs_of(self, user_id: UUID, post_id: UUID) -> list[str]:
        row = UserPostTagSet.objects(
            user_id=user_id, post_id=post_id
        ).first()
        if row is None:
            return []
        return list(row.slugs or [])

    def add_edge(
        self, user_id: UUID, slug: str, post_id: UUID, org_id: UUID
    ) -> None:
        UserPostTag.create(
            user_id=user_id, tag_slug=slug, post_id=post_id, org_id=org_id
        )

    def remove_edge(self, user_id: UUID, slug: str, post_id: UUID) -> None:
        UserPostTag.objects(
            user_id=user_id, tag_slug=slug, post_id=post_id
        ).delete()

    def write_set(
        self,
        user_id: UUID,
        post_id: UUID,
        org_id: UUID,
        slugs: list[str],
    ) -> None:
        if not slugs:
            UserPostTagSet.objects(
                user_id=user_id, post_id=post_id
            ).delete()
            return
        current = UserPostTagSet.objects(
            user_id=user_id, post_id=post_id
        ).first()
        if current is None:
            UserPostTagSet.create(
                user_id=user_id, post_id=post_id, org_id=org_id, slugs=slugs
            )
            return
        UserPostTagSet.objects(user_id=user_id, post_id=post_id).update(
            org_id=org_id, slugs=slugs
        )

    def sets_for(self, user_id: UUID) -> list[UserPostTagSet]:
        return list(UserPostTagSet.objects(user_id=user_id).all())

    def activities_for(
        self, user_id: UUID, slug: str
    ) -> list[UserActivityTag]:
        return list(
            UserActivityTag.objects(user_id=user_id, tag_slug=slug).all()
        )

    def activity_slugs_of(
        self, user_id: UUID, activity_id: UUID
    ) -> list[str]:
        row = UserActivityTagSet.objects(
            user_id=user_id, activity_id=activity_id
        ).first()
        if row is None:
            return []
        return list(row.slugs or [])

    def add_activity_edge(
        self, user_id: UUID, slug: str, activity_id: UUID, org_id: UUID
    ) -> None:
        UserActivityTag.create(
            user_id=user_id,
            tag_slug=slug,
            activity_id=activity_id,
            org_id=org_id,
        )

    def remove_activity_edge(
        self, user_id: UUID, slug: str, activity_id: UUID
    ) -> None:
        UserActivityTag.objects(
            user_id=user_id, tag_slug=slug, activity_id=activity_id
        ).delete()

    def write_activity_set(
        self,
        user_id: UUID,
        activity_id: UUID,
        org_id: UUID,
        slugs: list[str],
    ) -> None:
        if not slugs:
            UserActivityTagSet.objects(
                user_id=user_id, activity_id=activity_id
            ).delete()
            return
        current = UserActivityTagSet.objects(
            user_id=user_id, activity_id=activity_id
        ).first()
        if current is None:
            UserActivityTagSet.create(
                user_id=user_id,
                activity_id=activity_id,
                org_id=org_id,
                slugs=slugs,
            )
            return
        UserActivityTagSet.objects(
            user_id=user_id, activity_id=activity_id
        ).update(org_id=org_id, slugs=slugs)

    def activity_sets_for(self, user_id: UUID) -> list[UserActivityTagSet]:
        return list(UserActivityTagSet.objects(user_id=user_id).all())
