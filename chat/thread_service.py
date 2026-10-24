"""Room sub-threads: focused channels nested under a parent room.

A thread is a channel row carrying parent_room_id (the general room or
a top-level channel - threads never nest). The channel_id doubles as
the room id, so messages/reads/realtime need no thread-specific code;
this service only owns creation rules and the per-room listing. Any
room member may open a thread (unlike top-level channels, which are
manager-created), while kind/post-policy and archive stay governed by
the shared channel rules (creator or manager edits - see
ChannelService.update_channel).
"""

from __future__ import annotations

from uuid import UUID

from chat.channel_helpers import (
    can_open_channel,
    channel_manager,
    channel_row_or_404,
    require_event_creator,
    require_org_member,
)
from chat.channel_interfaces import ChannelStore
from chat.channel_service import CHANNEL_NAME_MAX, CHANNEL_TOPIC_MAX
from chat.dtos import ChannelSnapshot
from chat.interfaces import ActivityLookup, ChatEvents
from chat.rooms import emit_inbox
from core.exceptions import (
    ChannelArchivedError,
    ChannelNameTakenError,
    ForbiddenError,
    InvalidChannelStateError,
    NotFoundError,
)
from core.security import utc_aware, utcnow
from orgs.interfaces import MemberRepository, OrgRepository
from orgs.member_helpers import live_org
from rbac.interfaces import AccessControl


class ThreadService:
    """Sub-thread creation and per-room listing."""

    def __init__(
        self,
        channels: ChannelStore,
        orgs: OrgRepository,
        members: MemberRepository,
        access: AccessControl,
        events: ChatEvents,
        activities: ActivityLookup | None = None,
    ) -> None:
        self._channels = channels
        self._orgs = orgs
        self._members = members
        self._access = access
        self._events = events
        self._activities = activities

    def _snap(self, row) -> ChannelSnapshot:  # noqa: ANN001
        activity_id = getattr(row, "activity_id", None)
        activity_title = None
        if activity_id is not None and self._activities is not None:
            activity = self._activities.get(activity_id)
            activity_title = (
                getattr(activity, "title", None) if activity else None
            )
        return ChannelSnapshot(
            channel_id=row.channel_id,
            org_id=row.org_id,
            name=row.name,
            topic=row.topic or "",
            kind=row.kind,
            post_policy=row.post_policy,
            visibility=row.visibility,
            created_by=row.created_by,
            created_at=utc_aware(row.created_at),
            archived_at=utc_aware(row.archived_at),
            parent_room_id=getattr(row, "parent_room_id", None),
            activity_id=activity_id,
            activity_title=activity_title,
        )

    def _parent(self, org_id: UUID, parent_room_id: UUID, user_id: UUID):
        """Resolve + gate the parent room; returns (row, visibility).

        The general room (parent == org id) is open to every member. A
        channel parent must be top-level (threads never nest), live and
        openable by the caller; restricted parents mark the thread so
        its audience stays inherited.
        """
        if parent_room_id == org_id:
            return None, "org"
        row = channel_row_or_404(self._channels, org_id, parent_room_id)
        if getattr(row, "parent_room_id", None) is not None:
            raise InvalidChannelStateError(
                "Threads cannot nest inside other threads."
            )
        if row.archived_at is not None:
            raise ChannelArchivedError("This channel is archived.")
        org = live_org(self._orgs, org_id)
        if not can_open_channel(
            self._access, self._channels, org, row, user_id
        ):
            raise ForbiddenError("Only channel members can do this.")
        return row, "restricted" if row.visibility == "restricted" else "org"

    def create_thread(
        self,
        org_id: UUID,
        parent_room_id: UUID,
        actor_id: UUID,
        name: str,
        topic: str,
        kind: str,
        post_policy: str,
        activity_id: UUID | None = None,
    ) -> ChannelSnapshot:
        org = live_org(self._orgs, org_id)
        require_org_member(self._members, org, actor_id)
        if activity_id is not None:
            require_event_creator(self._access, org, actor_id)
        _parent_row, visibility = self._parent(
            org_id, parent_room_id, actor_id
        )
        if activity_id is not None:
            activity = (
                self._activities.get(activity_id)
                if self._activities is not None
                else None
            )
            if activity is None or activity.org_id != org_id:
                raise NotFoundError("Activity not found.")
        name = (name or "").strip()
        if not name or len(name) > CHANNEL_NAME_MAX:
            raise InvalidChannelStateError(
                f"Thread name needs 1-{CHANNEL_NAME_MAX} characters."
            )
        topic = (topic or "").strip()[:CHANNEL_TOPIC_MAX]
        row = self._channels.create_channel(
            org_id, name, topic, kind, post_policy, visibility,
            actor_id, utcnow(),
            parent_room_id=parent_room_id, activity_id=activity_id,
        )
        if row is None:
            raise ChannelNameTakenError(
                "A thread with that name exists in this room."
            )
        emit_inbox(self._events, "channel.created", row.channel_id, org_id)
        self._access.record(
            org_id, actor_id, "thread.create", "chat",
            row.channel_id, "allowed",
        )
        return self._snap(row)

    def list_room_threads(
        self, org_id: UUID, parent_room_id: UUID, viewer_id: UUID
    ) -> list[ChannelSnapshot]:
        """Live threads of one room; managers also see archived rows."""
        org = live_org(self._orgs, org_id)
        require_org_member(self._members, org, viewer_id)
        if parent_room_id != org_id:
            row = channel_row_or_404(
                self._channels, org_id, parent_room_id
            )
            if getattr(row, "parent_room_id", None) is not None:
                raise InvalidChannelStateError(
                    "Threads cannot nest inside other threads."
                )
            if not can_open_channel(
                self._access, self._channels, org, row, viewer_id
            ):
                raise ForbiddenError("Only channel members can do this.")
        manager = channel_manager(self._access, org, viewer_id)
        return [
            self._snap(row)
            for row in self._channels.list_room_threads(parent_room_id)
            if row.archived_at is None or manager
        ]
