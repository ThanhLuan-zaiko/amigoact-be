"""Unit tests for ChannelService and channel room gates."""

from __future__ import annotations

from uuid import UUID

import pytest

from chat.channel_roster import ChannelRosterService
from chat.channel_service import ChannelService
from chat.composer import ChatComposer
from chat.inbox_service import ChatInboxService
from chat.service import ChatService
from chat.thread_service import ThreadService
from core.exceptions import (
    ChannelArchivedError,
    ChannelNameTakenError,
    ForbiddenError,
    InvalidChannelStateError,
    MemberNotFoundError,
    NotFoundError,
)
from tests.unit.channel_fakes import FakeChannelStore
from tests.unit.member_fakes import (
    FakeAccess,
    FakeMembers,
    FakeOrgs,
    FakeUsers,
)
from tests.unit.org_fakes import FakeMedia
from tests.unit.chat_fakes import (
    FakeActivities,
    FakeChatEvents,
    FakeChatStore,
    FakeUploader,
)
from tests.unit.workspace_fakes import (
    NOW,
    _uid,
    add_org,
)


def _world():
    """Services over shared fakes; returns a tuple of every handle."""
    chat, channels = FakeChatStore(), FakeChannelStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, events = FakeAccess(), FakeChatEvents()
    activities = FakeActivities()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    service = ChannelService(
        channels, orgs, members, users, access, events,
        media=FakeMedia(), activities=activities,
    )
    roster = ChannelRosterService(
        channels, orgs, members, users, access, media=FakeMedia(),
    )
    threads = ThreadService(
        channels, orgs, members, access, events, activities,
    )
    composer = ChatComposer(
        chat, orgs, members, users, access, events,
        FakeMedia(), FakeUploader(), activities, channels=channels,
    )
    rooms = ChatService(
        chat, orgs, members, users, access, events, activities,
        media=FakeMedia(), composer=composer, channels=channels,
    )
    return (
        service, roster, threads, rooms, chat, channels, orgs, members,
        users, access, org_id, owner,
    )


def _member(members, users, org_id: UUID, email: str = "m@x.com") -> UUID:  # noqa: ANN001
    uid = _uid()
    users.add(uid, email, f"Name {email}")
    members.put(org_id, uid, "active", NOW)
    return uid


def _manager(access, members, users, org_id: UUID) -> UUID:  # noqa: ANN001
    uid = _member(members, users, org_id, "mgr@x.com")
    access.perms.setdefault((org_id, uid), set()).add("chat:manage")
    return uid


def _create(svc, org_id, actor, **kw):  # noqa: ANN001, ANN201, ANN202
    args = dict(
        name="general-chat", topic="", kind="text",
        post_policy="everyone", visibility="org", member_ids=(),
    )
    args.update(kw)
    return svc.create_channel(org_id, actor, **args)


def test_create_requires_manager() -> None:
    svc, _, _, _, _, _, _, members, users, _, org_id, _ = _world()
    member = _member(members, users, org_id)
    with pytest.raises(ForbiddenError):
        _create(svc, org_id, member)


def test_create_and_name_conflict() -> None:
    svc, *_rest, org_id, owner = _world()
    snap = _create(svc, org_id, owner, name="Reports", topic="Weekly")
    assert snap.name == "Reports"
    assert snap.kind == "text"
    with pytest.raises(ChannelNameTakenError):
        _create(svc, org_id, owner, name="REPORTS")


def test_archive_releases_name_and_rearchive_conflict() -> None:
    svc, *_rest, org_id, owner = _world()
    snap = _create(svc, org_id, owner, name="old-room")
    svc.update_channel(org_id, snap.channel_id, owner, archived=True)
    other = _create(svc, org_id, owner, name="OLD-ROOM")
    with pytest.raises(ChannelNameTakenError):
        svc.update_channel(
            org_id, snap.channel_id, owner, archived=False
        )
    svc.update_channel(org_id, other.channel_id, owner, archived=True)
    revived = svc.update_channel(
        org_id, snap.channel_id, owner, archived=False
    )
    assert revived.archived_at is None


def test_rename_conflict_and_release() -> None:
    svc, *_rest, org_id, owner = _world()
    first = _create(svc, org_id, owner, name="alpha")
    second = _create(svc, org_id, owner, name="beta")
    with pytest.raises(ChannelNameTakenError):
        svc.update_channel(org_id, second.channel_id, owner, name="ALPHA")
    svc.update_channel(org_id, first.channel_id, owner, name="gamma")
    renamed = svc.update_channel(
        org_id, second.channel_id, owner, name="alpha"
    )
    assert renamed.name == "alpha"


def test_restricted_acl() -> None:
    (
        svc, roster, _, rooms, _, _channels, _orgs,
        members, users, access, org_id, owner,
    ) = _world()
    member = _member(members, users, org_id)
    snap = _create(svc, org_id, owner, visibility="restricted")
    with pytest.raises(ForbiddenError):
        rooms.list_messages(snap.channel_id, member)
    assert rooms.list_messages(snap.channel_id, owner).items == []
    mgr = _manager(access, members, users, org_id)
    assert rooms.list_messages(snap.channel_id, mgr).items == []
    roster.add_channel_member(org_id, snap.channel_id, owner, member)
    assert rooms.list_messages(snap.channel_id, member).items == []


def test_post_policy_managers() -> None:
    (
        svc, _roster, _threads, rooms, _chat, _ch, _o,
        members, users, access, org_id, owner,
    ) = _world()
    snap = _create(svc, org_id, owner, post_policy="managers")
    member = _member(members, users, org_id)
    with pytest.raises(ForbiddenError):
        rooms.send_message(snap.channel_id, member, "hi")
    mgr = _manager(access, members, users, org_id)
    assert rooms.send_message(snap.channel_id, mgr, "ok").body == "ok"
    assert rooms.send_message(snap.channel_id, owner, "boss").body == "boss"


def test_archived_gates_writes() -> None:
    (
        svc, _r, _t, rooms, _c, _ch, _o,
        members, users, _a, org_id, owner,
    ) = _world()
    snap = _create(svc, org_id, owner)
    sent = rooms.send_message(snap.channel_id, owner, "before")
    svc.update_channel(org_id, snap.channel_id, owner, archived=True)
    member = _member(members, users, org_id)
    with pytest.raises(ChannelArchivedError):
        rooms.send_message(snap.channel_id, owner, "after")
    with pytest.raises(ChannelArchivedError):
        rooms.edit_message(snap.channel_id, owner, sent.message_id, "x")
    with pytest.raises(ChannelArchivedError):
        rooms.toggle_reaction(snap.channel_id, owner, sent.message_id, "\U0001F44D")
    # Reads stay open so history is reviewable.
    assert rooms.list_messages(snap.channel_id, member).items


def test_seat_management_rules() -> None:
    (
        svc, roster_svc, _t, _r, _c, _ch, _o,
        members, users, _a, org_id, owner,
    ) = _world()
    member = _member(members, users, org_id)
    open_row = _create(svc, org_id, owner, name="open")
    with pytest.raises(InvalidChannelStateError):
        roster_svc.add_channel_member(
            org_id, open_row.channel_id, owner, member
        )
    row = _create(svc, org_id, owner, name="locked", visibility="restricted")
    outsider = _uid()
    with pytest.raises(MemberNotFoundError):
        roster_svc.add_channel_member(org_id, row.channel_id, owner, outsider)
    seat = roster_svc.add_channel_member(
        org_id, row.channel_id, owner, member
    )
    assert seat.full_name.startswith("Name")
    with pytest.raises(NotFoundError):
        roster_svc.remove_channel_member(
            org_id, row.channel_id, owner, _uid()
        )
    roster_svc.remove_channel_member(org_id, row.channel_id, owner, member)
    roster = roster_svc.list_channel_members(org_id, row.channel_id, owner)
    assert {item.user_id for item in roster} == {owner}


def test_list_channels_visibility() -> None:
    (
        svc, roster_svc, _t, _r, _c, _ch, _o,
        members, users, access, org_id, owner,
    ) = _world()
    member = _member(members, users, org_id)
    mgr = _manager(access, members, users, org_id)
    _create(svc, org_id, owner, name="public")
    locked = _create(
        svc, org_id, owner, name="secret", visibility="restricted"
    )
    svc.update_channel(
        org_id, _create(svc, org_id, owner, name="gone").channel_id,
        owner, archived=True,
    )
    names = {c.name for c in svc.list_channels(org_id, member)}
    assert names == {"public"}
    # Managers also see archived rows so they can restore them.
    names = {c.name for c in svc.list_channels(org_id, mgr)}
    assert names == {"public", "secret", "gone"}
    roster_svc.add_channel_member(
        org_id, locked.channel_id, owner, member
    )
    names = {c.name for c in svc.list_channels(org_id, member)}
    assert names == {"public", "secret"}


def test_inbox_enumerates_visible_channels() -> None:
    (
        svc, _roster, _threads, _rooms, chat, channels, orgs,
        members, users, access, org_id, owner,
    ) = _world()
    member = _member(members, users, org_id)
    svc.create_channel(
        org_id, owner, "reports", "", "report", "managers",
        "org", (),
    )
    svc.create_channel(
        org_id, owner, "secret", "", "text", "everyone",
        "restricted", (),
    )
    inbox = ChatInboxService(
        chat, orgs, members, users, FakeActivities(),
        media=FakeMedia(), channels=channels, access=access,
    )
    rows = {row.title: row for row in inbox.list_inbox(member)}
    assert rows["reports"].kind == "channel"
    assert rows["reports"].post_policy == "managers"
    assert rows["reports"].channel_kind == "report"
    assert "secret" not in rows
    rows = {row.title: row for row in inbox.list_inbox(owner)}
    assert "secret" in rows
