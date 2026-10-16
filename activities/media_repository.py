"""cqlengine persistence for the activity_media gallery."""

from __future__ import annotations

from uuid import UUID

from activities.interfaces import ActivityMediaStore
from activities.model import ActivityMedia


class CqlActivityMediaStore(ActivityMediaStore):
    """Ordered gallery entries; asset metadata lives in media_assets."""

    def list_for_activity(self, activity_id: UUID) -> list[ActivityMedia]:
        return list(ActivityMedia.objects(activity_id=activity_id).all())

    def create(
        self,
        activity_id: UUID,
        position: int,
        asset_id: UUID,
        role: str,
        caption: str | None,
    ) -> ActivityMedia:
        return ActivityMedia.create(
            activity_id=activity_id,
            position=position,
            asset_id=asset_id,
            role=role,
            caption=caption,
        )

    def update(
        self,
        activity_id: UUID,
        position: int,
        asset_id: UUID,
        caption: str | None,
        role: str,
    ) -> None:
        ActivityMedia.objects(
            activity_id=activity_id,
            position=position,
            asset_id=asset_id,
        ).update(caption=caption, role=role)

    def delete(self, activity_id: UUID, position: int, asset_id: UUID) -> None:
        ActivityMedia.objects(
            activity_id=activity_id,
            position=position,
            asset_id=asset_id,
        ).delete()
