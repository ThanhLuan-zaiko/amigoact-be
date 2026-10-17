"""Shared in-memory ChannelStore port for channel unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from chat.channel_interfaces import ChannelStore
from tests.unit.workspace_fakes import _uid


class FakeChannelStore(ChannelStore):
    """Channel rows, name claims, and restricted seats in dicts."""

    def __init__(self) -> None:
        self.channels: dict[UUID, Any] = {}
        self.names: dict[tuple[UUID, str], UUID] = {}
        self.seats: dict[tuple[UUID, UUID], Any] = {}

    def create_channel(  # noqa: ANN201
        self, org_id, name, topic, kind, post_policy, visibility,
        created_by, now,
    ):
        channel_id = _uid()
        folded = name.casefold()
        if not self.claim_name(org_id, folded, channel_id, now):
            return None
        row = SimpleNamespace(
            channel_id=channel_id, org_id=org_id, name=name,
            name_folded=folded, topic=topic, kind=kind,
            post_policy=post_policy, visibility=visibility,
            created_by=created_by, created_at=now,
            archived_at=None, archived_by=None,
        )
        self.channels[channel_id] = row
        return row

    def get_channel(self, channel_id):  # noqa: ANN001, ANN202
        return self.channels.get(channel_id)

    def get_channel_in_org(self, org_id, channel_id):  # noqa: ANN001, ANN202
        row = self.channels.get(channel_id)
        return row if row is not None and row.org_id == org_id else None

    def list_channels(self, org_id):  # noqa: ANN001, ANN202
        return [
            row for row in self.channels.values() if row.org_id == org_id
        ]

    def update_channel(self, channel):  # noqa: ANN001, ANN202
        self.channels[channel.channel_id] = channel

    def claim_name(self, org_id, name_folded, channel_id, now):  # noqa: ANN001, ANN202
        holder = self.names.get((org_id, name_folded))
        if holder is None or holder == channel_id:
            self.names[(org_id, name_folded)] = channel_id
            return True
        held = self.channels.get(holder)
        if held is not None and held.archived_at is None:
            return False
        self.names[(org_id, name_folded)] = channel_id
        return True

    def release_name(self, org_id, name_folded):  # noqa: ANN001, ANN202
        self.names.pop((org_id, name_folded), None)

    def add_channel_member(  # noqa: ANN201
        self, channel_id, org_id, user_id, added_by, now,
    ):
        self.seats[(channel_id, user_id)] = SimpleNamespace(
            channel_id=channel_id, org_id=org_id, user_id=user_id,
            added_by=added_by, added_at=now,
        )

    def remove_channel_member(self, channel_id, user_id):  # noqa: ANN001, ANN202
        self.seats.pop((channel_id, user_id), None)

    def get_channel_member(self, channel_id, user_id):  # noqa: ANN001, ANN202
        return self.seats.get((channel_id, user_id))

    def list_channel_members(self, channel_id):  # noqa: ANN001, ANN202
        return [
            row for (cid, _), row in self.seats.items()
            if cid == channel_id
        ]

    def list_channel_memberships(self, user_id):  # noqa: ANN001, ANN202
        return [
            row for (_, uid), row in self.seats.items()
            if uid == user_id
        ]
