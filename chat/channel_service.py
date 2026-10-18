"""Named-channel lifecycle: create, list, update, archive.

channel_id doubles as the room id (open_room resolves it), so this
service only owns channel metadata; posting gates live in the composer,
restricted rosters in channel_roster.ChannelRosterService and room
sub-threads in thread_service.ThreadService.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from chat.channel_helpers import (
    channel_manager,
    channel_row_or_404,
    require_channel_manager,
    require_org_member,
)
from chat.channel_interfaces import ChannelStore
from chat.dtos import ChannelSnapshot
from chat.interfaces import ActivityLookup, ChatEvents
from chat.rooms import emit_inbox
from core.exceptions import (
    ChannelNameTakenError,
    ForbiddenError,
    InvalidChannelStateError,
    MemberNotFoundError,
)
from core.security import utc_aware, utcnow
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from orgs.member_helpers import is_active_member, live_org
from orgs.model import Organization
from rbac.interfaces import AccessControl

CHANNEL_NAME_MAX = 80
CHANNEL_TOPIC_MAX = 200


class ChannelService:
    """Channel CRUD for the org-wide directory.

    Managers own every field; a sub-thread's creator may rename,
    retopic and archive their own thread while kind/post-policy stay
    manager-only and visibility stays derived from the parent.
    """

    def __init__(
        self,
        channels: ChannelStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        access: AccessControl,
        events: ChatEvents,
        media: MediaRepository | None = None,
        activities: ActivityLookup | None = None,
    ) -> None:
        self._channels = channels
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events
        self._media = media
        self._activities = activities

    @staticmethod
    def _scope(row) -> UUID:  # noqa: ANN001
        """Name-claim scope: the parent room for threads, else the org."""
        return row.parent_room_id or row.org_id

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

    def _fan(self, action: str, channel_id: UUID, org_id: UUID) -> None:
        emit_inbox(self._events, action, channel_id, org_id)

    def list_channels(
        self, org_id: UUID, viewer_id: UUID
    ) -> list[ChannelSnapshot]:
        """Visible channels: org-wide live ones, plus restricted rooms
        the viewer sits on. Managers additionally see archived rows so
        they can restore them. Sub-threads never list here - they belong
        to their parent room (ThreadService.list_room_threads)."""
        org = live_org(self._orgs, org_id)
        require_org_member(self._members, org, viewer_id)
        manager = channel_manager(self._access, org, viewer_id)
        seats = {
            row.channel_id
            for row in self._channels.list_channel_memberships(viewer_id)
        }
        return [
            self._snap(row)
            for row in self._channels.list_channels(org_id)
            if getattr(row, "parent_room_id", None) is None
            and (row.archived_at is None or manager)
            and (
                row.visibility != "restricted"
                or manager
                or row.channel_id in seats
            )
        ]

    def create_channel(
        self,
        org_id: UUID,
        actor_id: UUID,
        name: str,
        topic: str,
        kind: str,
        post_policy: str,
        visibility: str,
        member_ids: list[UUID] | tuple[UUID, ...] = (),
    ) -> ChannelSnapshot:
        org = live_org(self._orgs, org_id)
        require_channel_manager(self._access, org, actor_id)
        name = (name or "").strip()
        if not name or len(name) > CHANNEL_NAME_MAX:
            raise InvalidChannelStateError(
                f"Channel name needs 1-{CHANNEL_NAME_MAX} characters."
            )
        topic = (topic or "").strip()[:CHANNEL_TOPIC_MAX]
        now = utcnow()
        row = self._channels.create_channel(
            org_id, name, topic, kind, post_policy, visibility,
            actor_id, now,
        )
        if row is None:
            raise ChannelNameTakenError("A channel with that name exists.")
        if visibility == "restricted":
            self._seed_seats(row, org, actor_id, tuple(member_ids), now)
        self._fan("channel.created", row.channel_id, org_id)
        self._access.record(
            org_id, actor_id, "channel.create", "chat",
            row.channel_id, "allowed",
        )
        return self._snap(row)

    def _seed_seats(
        self,
        row,
        org: Organization,
        actor_id: UUID,
        member_ids: tuple[UUID, ...],
        now: datetime,
    ) -> None:
        """Creator plus invited roster for a restricted channel."""
        for user_id in {actor_id, *member_ids}:
            if user_id != org.owner_id and not is_active_member(
                self._members, row.org_id, user_id
            ):
                raise MemberNotFoundError(
                    "Channel seats require active org members."
                )
            self._channels.add_channel_member(
                row.channel_id, row.org_id, user_id, actor_id, now
            )

    def update_channel(
        self,
        org_id: UUID,
        channel_id: UUID,
        actor_id: UUID,
        *,
        name: str | None = None,
        topic: str | None = None,
        kind: str | None = None,
        post_policy: str | None = None,
        visibility: str | None = None,
        archived: bool | None = None,
    ) -> ChannelSnapshot:
        org = live_org(self._orgs, org_id)
        row = channel_row_or_404(self._channels, org_id, channel_id)
        manager = channel_manager(self._access, org, actor_id)
        creator = (
            getattr(row, "parent_room_id", None) is not None
            and row.created_by == actor_id
        )
        if not manager and not creator:
            self._access.record(
                org.id, actor_id, "channel.update", "chat",
                channel_id, "denied",
            )
            raise ForbiddenError("Only chat managers can do this.")
        if not manager and (
            kind is not None
            or post_policy is not None
            or visibility is not None
        ):
            raise ForbiddenError("Only chat managers can do this.")
        if row.parent_room_id is not None and visibility is not None:
            raise InvalidChannelStateError(
                "Threads inherit the parent room's audience."
            )
        now = utcnow()
        release: str | None = None
        if name is not None:
            clean = name.strip()
            if not clean or len(clean) > CHANNEL_NAME_MAX:
                raise InvalidChannelStateError(
                    f"Channel name needs 1-{CHANNEL_NAME_MAX} characters."
                )
            if clean.casefold() != row.name_folded:
                if not self._channels.claim_name(
                    self._scope(row), clean.casefold(), channel_id, now
                ):
                    raise ChannelNameTakenError(
                        "A channel with that name exists."
                    )
                release = row.name_folded
                row.name, row.name_folded = clean, clean.casefold()
        if topic is not None:
            row.topic = topic.strip()[:CHANNEL_TOPIC_MAX]
        if kind is not None:
            row.kind = kind
        if post_policy is not None:
            row.post_policy = post_policy
        if visibility is not None:
            row.visibility = visibility
        if archived is not None:
            self._set_archived(row, org, actor_id, archived, now)
        self._channels.update_channel(row)
        if release is not None:
            self._channels.release_name(self._scope(row), release)
        self._fan("channel.updated", channel_id, org_id)
        self._access.record(
            org_id, actor_id, "channel.update", "chat",
            channel_id, "allowed",
        )
        return self._snap(row)

    def _set_archived(
        self,
        row,
        org: Organization,
        actor_id: UUID,
        archived: bool,
        now: datetime,
    ) -> None:
        scope = self._scope(row)
        if archived and row.archived_at is None:
            row.archived_at, row.archived_by = now, actor_id
            self._channels.release_name(scope, row.name_folded)
        elif not archived and row.archived_at is not None:
            if not self._channels.claim_name(
                scope, row.name_folded, row.channel_id, now
            ):
                raise ChannelNameTakenError(
                    "A channel with that name exists."
                )
            row.archived_at = row.archived_by = None
