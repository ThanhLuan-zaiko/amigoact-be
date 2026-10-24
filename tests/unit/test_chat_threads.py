"""Unit tests for room sub-threads (ThreadService + inherited gates)."""

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
    ChannelNotFoundError,
    ForbiddenError,
    InvalidChannelStateError,
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
    make_attachments,
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
        FakeMedia(), make_attachments(), activities, channels=channels,
    )
    rooms = ChatService(
        chat, orgs, members, users, access, events, activities,
        media=FakeMedia(), composer=composer, channels=channels,
    )
    return (
        service, roster, threads, rooms, chat, channels, orgs, members,
        users, access, org_id, owner, activities,
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


def _channel(svc, org_id, actor, **kw):  # noqa: ANN001, ANN201, ANN202
    args = dict(
        name="parent-channel", topic="", kind="text",
        post_policy="everyone", visibility="org", member_ids=(),
    )
    args.update(kw)
    return svc.create_channel(org_id, actor, **args)


def _thread(threads, org_id, parent_id, actor, **kw):  # noqa: ANN001, ANN201, ANN202
    args = dict(
        name="focus-topic", topic="", kind="text",
        post_policy="everyone", activity_id=None,
    )
    args.update(kw)
    return threads.create_thread(org_id, parent_id, actor, **args)


def test_member_creates_thread_in_general_room() -> None:
    (_s, _r, threads, _rooms, _c, _ch, _o,
     members, users, _a, org_id, _owner, _acts,) = _world()
    member = _member(members, users, org_id)
    snap = _thread(threads, org_id, org_id, member)
    assert snap.parent_room_id == org_id
    assert snap.visibility == "org"
    assert snap.created_by == member
    listed = threads.list_room_threads(org_id, org_id, member)
    assert [row.channel_id for row in listed] == [snap.channel_id]


def test_outsider_and_non_members_cannot_create() -> None:
    (_s, _r, threads, _rooms, _c, _ch, _o,
     _m, _u, _a, org_id, _owner, _acts,) = _world()
    with pytest.raises(ForbiddenError):
        _thread(threads, org_id, org_id, _uid())


def test_member_creates_thread_under_channel() -> None:
    (svc, _r, threads, _rooms, _c, _ch, _o,
     members, users, _a, org_id, owner, _acts,) = _world()
    member = _member(members, users, org_id)
    parent = _channel(svc, org_id, owner)
    snap = _thread(threads, org_id, parent.channel_id, member)
    assert snap.parent_room_id == parent.channel_id


def test_threads_never_nest() -> None:
    (_s, _r, threads, _rooms, _c, _ch, _o,
     members, users, _a, org_id, _owner, _acts,) = _world()
    member = _member(members, users, org_id)
    snap = _thread(threads, org_id, org_id, member)
    with pytest.raises(InvalidChannelStateError):
        _thread(threads, org_id, snap.channel_id, member)


def test_thread_rejected_under_unknown_room() -> None:
    (_s, _r, threads, _rooms, _c, _ch, _o,
     members, users, _a, org_id, _owner, _acts,) = _world()
    member = _member(members, users, org_id)
    with pytest.raises(ChannelNotFoundError):
        _thread(threads, org_id, _uid(), member)


def test_thread_names_unique_per_parent() -> None:
    (svc, _r, threads, _rooms, _c, _ch, _o,
     members, users, _a, org_id, owner, _acts,) = _world()
    member = _member(members, users, org_id)
    parent = _channel(svc, org_id, owner)
    _thread(threads, org_id, org_id, member, name="same-name")
    # Same folded name under a different parent is a different scope.
    _thread(threads, org_id, parent.channel_id, member, name="SAME-NAME")
    with pytest.raises(ChannelNameTakenError):
        _thread(threads, org_id, org_id, member, name="Same-Name")


def test_thread_under_archived_channel_rejected() -> None:
    (svc, _r, threads, _rooms, _c, _ch, _o,
     members, users, _a, org_id, owner, _acts,) = _world()
    member = _member(members, users, org_id)
    parent = _channel(svc, org_id, owner)
    svc.update_channel(org_id, parent.channel_id, owner, archived=True)
    with pytest.raises(ChannelArchivedError):
        _thread(threads, org_id, parent.channel_id, member)


def test_restricted_parent_inherits_roster_gate() -> None:
    (svc, roster, threads, rooms, _c, _ch, _o,
     members, users, _a, org_id, owner, _acts,) = _world()
    outsider = _member(members, users, org_id, "out@x.com")
    seated = _member(members, users, org_id, "in@x.com")
    parent = _channel(svc, org_id, owner, visibility="restricted")
    roster.add_channel_member(org_id, parent.channel_id, owner, seated)
    with pytest.raises(ForbiddenError):
        _thread(threads, org_id, parent.channel_id, outsider)
    snap = _thread(threads, org_id, parent.channel_id, seated)
    assert snap.visibility == "restricted"
    # open_room gates the thread through the parent's seats.
    with pytest.raises(ForbiddenError):
        rooms.list_messages(snap.channel_id, outsider)
    assert rooms.list_messages(snap.channel_id, seated).items == []
    assert rooms.list_messages(snap.channel_id, owner).items == []


def test_thread_creator_edits_own_thread() -> None:
    (svc, _r, threads, _rooms, _c, _ch, _o,
     members, users, access, org_id, _owner, _acts,) = _world()
    creator = _member(members, users, org_id, "c@x.com")
    other = _member(members, users, org_id, "o@x.com")
    snap = _thread(threads, org_id, org_id, creator)
    renamed = svc.update_channel(
        org_id, snap.channel_id, creator, name="Renamed"
    )
    assert renamed.name == "Renamed"
    with pytest.raises(ForbiddenError):
        svc.update_channel(
            org_id, snap.channel_id, other, name="hijack"
        )
    mgr = _manager(access, members, users, org_id)
    svc.update_channel(org_id, snap.channel_id, mgr, archived=True)


def test_creator_cannot_change_kind_policy_or_visibility() -> None:
    (svc, _r, threads, _rooms, _c, _ch, _o,
     members, users, access, org_id, owner, _acts,) = _world()
    creator = _member(members, users, org_id, "c@x.com")
    snap = _thread(threads, org_id, org_id, creator)
    with pytest.raises(ForbiddenError):
        svc.update_channel(org_id, snap.channel_id, creator, kind="task")
    with pytest.raises(ForbiddenError):
        svc.update_channel(
            org_id, snap.channel_id, creator, visibility="restricted"
        )
    # Even managers cannot retarget a thread's audience: it is derived
    # from the parent room.
    with pytest.raises(InvalidChannelStateError):
        svc.update_channel(
            org_id, snap.channel_id, owner, visibility="restricted"
        )
    mgr = _manager(access, members, users, org_id)
    with pytest.raises(InvalidChannelStateError):
        svc.update_channel(
            org_id, snap.channel_id, mgr, visibility="org"
        )


def test_threads_stay_out_of_channel_directory() -> None:
    (svc, _r, threads, _rooms, _c, _ch, _o,
     members, users, _a, org_id, owner, _acts,) = _world()
    member = _member(members, users, org_id)
    _channel(svc, org_id, owner, name="directory-row")
    _thread(threads, org_id, org_id, member, name="nested-only")
    names = {row.name for row in svc.list_channels(org_id, member)}
    assert names == {"directory-row"}


def test_thread_activity_link_validation() -> None:
    (_s, _r, threads, _rooms, _c, _ch, _o,
     members, users, access, org_id, _owner, acts,) = _world()
    creator = _member(members, users, org_id)
    access.perms.setdefault((org_id, creator), set()).add("activity:create")
    activity_id = _uid()
    acts.add(activity_id, org_id, "Beach cleanup")
    snap = _thread(
        threads, org_id, org_id, creator, activity_id=activity_id
    )
    assert snap.activity_id == activity_id
    assert snap.activity_title == "Beach cleanup"
    with pytest.raises(NotFoundError):
        _thread(threads, org_id, org_id, creator, activity_id=_uid())
    foreign = _uid()
    acts.add(foreign, _uid(), "Other org")
    with pytest.raises(NotFoundError):
        _thread(threads, org_id, org_id, creator, activity_id=foreign)


def test_inbox_lists_threads_and_hides_restricted() -> None:
    (svc, roster, threads, _rooms, chat, channels, orgs,
     members, users, access, org_id, owner, _acts,) = _world()
    member = _member(members, users, org_id, "open@x.com")
    hidden = _member(members, users, org_id, "hid@x.com")
    _thread(threads, org_id, org_id, member, name="inbox-thread")
    locked = _channel(
        svc, org_id, owner, name="locked-parent",
        visibility="restricted",
    )
    roster.add_channel_member(org_id, locked.channel_id, owner, member)
    _thread(
        threads, org_id, locked.channel_id, member,
        name="secret-thread",
    )
    inbox = ChatInboxService(
        chat, orgs, members, users, FakeActivities(),
        media=FakeMedia(), channels=channels, access=access,
    )
    titles = {row.title: row for row in inbox.list_inbox(member)}
    assert titles["inbox-thread"].parent_room_id == org_id
    assert titles["secret-thread"].parent_room_id == locked.channel_id
    # A non-seated member sees the org-wide thread but never the
    # restricted-parent one.
    titles = {row.title: row for row in inbox.list_inbox(hidden)}
    assert "inbox-thread" in titles
    assert "secret-thread" not in titles


def test_list_room_threads_gates_like_parent() -> None:
    (svc, roster, threads, _rooms, _c, _ch, _o,
     members, users, access, org_id, owner, _acts,) = _world()
    member = _member(members, users, org_id, "m@x.com")
    parent = _channel(svc, org_id, owner, visibility="restricted")
    roster.add_channel_member(org_id, parent.channel_id, owner, member)
    _thread(threads, org_id, parent.channel_id, member)
    outsider = _member(members, users, org_id, "o@x.com")
    with pytest.raises(ForbiddenError):
        threads.list_room_threads(org_id, parent.channel_id, outsider)
    assert len(
        threads.list_room_threads(org_id, parent.channel_id, member)
    ) == 1
    # Managers see archived threads too.
    snap = threads.list_room_threads(
        org_id, parent.channel_id, member
    )[0]
    svc.update_channel(org_id, snap.channel_id, owner, archived=True)
    mgr = _manager(access, members, users, org_id)
    assert len(
        threads.list_room_threads(org_id, parent.channel_id, mgr)
    ) == 1
    assert (
        threads.list_room_threads(org_id, parent.channel_id, member)
        == []
    )


def test_roster_calls_on_thread_rows_rejected() -> None:
    (_s, roster, threads, _rooms, _c, _ch, _o,
     members, users, _a, org_id, owner, _acts,) = _world()
    member = _member(members, users, org_id)
    snap = _thread(threads, org_id, org_id, member)
    with pytest.raises(InvalidChannelStateError):
        roster.add_channel_member(
            org_id, snap.channel_id, owner, member
        )
    with pytest.raises(InvalidChannelStateError):
        roster.remove_channel_member(
            org_id, snap.channel_id, owner, member
        )
