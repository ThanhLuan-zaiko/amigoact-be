"""Unit tests for ChatService: sends, history walk, unread, moderation."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from chat.composer import ChatComposer
from chat.helpers import bucket_of, bucket_of_uuid, prev_bucket
from chat.service import ChatService
from core.exceptions import (
    ForbiddenError,
    InvalidMemberStateError,
    MemberNotFoundError,
    NotFoundError,
)
from core.security import utcnow
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


def _service(media: FakeMedia | None = None):
    chat = FakeChatStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, events = FakeAccess(), FakeChatEvents()
    activities = FakeActivities()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    media = media if media is not None else FakeMedia()
    uploader = FakeUploader()
    service = ChatService(
        chat, orgs, members, users, access, events, activities,
        media=media,
        composer=ChatComposer(
            chat, orgs, members, users, access, events,
            media, uploader, activities,
        ),
    )
    return (
        service, chat, orgs, members, users, access, events,
        activities, org_id, owner,
    )


def _member(
    members: FakeMembers, users: FakeUsers, org_id: UUID,
    email: str = "mem@x.com",
) -> UUID:
    uid = _uid()
    users.add(uid, email, f"Name {email}")
    members.put(org_id, uid, "active", NOW)
    return uid


def test_send_requires_membership() -> None:
    svc, _, _, _, _, access, _, _, org_id, _ = _service()
    with pytest.raises(ForbiddenError):
        svc.send_message(org_id, _uid(), "hi")
    with pytest.raises(ForbiddenError):
        svc.list_messages(org_id, _uid())
    assert ("chat.send", None, "denied") in access.audit


def test_send_then_list_returns_oldest_first() -> None:
    svc, _, _, _, _, _, events, _, org_id, owner = _service()
    first = svc.send_message(org_id, owner, "m1")
    second = svc.send_message(org_id, owner, "m2")
    page = svc.list_messages(org_id, owner)
    assert [m.message_id for m in page.items] == [
        first.message_id, second.message_id
    ]
    assert page.next_cursor is None
    assert page.unread == 0  # own sends never inflate the sender badge
    assert events.calls[-1][1] == "message.created"


def test_history_cursor_pages_back() -> None:
    svc, _, _, _, _, _, _, _, org_id, owner = _service()
    ids = [
        svc.send_message(org_id, owner, f"m{i}").message_id
        for i in range(5)
    ]
    page = svc.list_messages(org_id, owner, limit=2)
    assert [m.message_id for m in page.items] == ids[3:]
    older = svc.list_messages(
        org_id, owner, limit=2, cursor=page.next_cursor
    )
    assert [m.message_id for m in older.items] == ids[1:3]
    oldest = svc.list_messages(
        org_id, owner, limit=2, cursor=older.next_cursor
    )
    assert [m.message_id for m in oldest.items] == ids[:1]
    assert oldest.next_cursor is None


def test_bucket_walk_survives_empty_months() -> None:
    (svc, chat, orgs, _, _, _, _, _, org_id, owner) = _service()
    # Org is old enough to reach ten months back.
    orgs.orgs[org_id].created_at = utcnow() - timedelta(days=320)
    current = bucket_of(utcnow())
    old_bucket = current
    for _ in range(8):
        old_bucket = prev_bucket(old_bucket)
    old_dt = utcnow() - timedelta(days=250)
    chat.create(org_id, old_bucket, _uid(), owner, "ancient", old_dt)
    # First page scans six empty buckets then hands back a bb: marker.
    page = svc.list_messages(org_id, owner)
    assert page.items == []
    assert page.next_cursor is not None
    assert page.next_cursor.startswith("bb:")
    resumed = svc.list_messages(
        org_id, owner, cursor=page.next_cursor
    )
    assert [m.body for m in resumed.items] == ["ancient"]
    assert resumed.next_cursor is None


def test_bucket_of_uuid_matches_created_bucket() -> None:
    svc, _, _, _, _, _, _, _, org_id, owner = _service()
    snap = svc.send_message(org_id, owner, "x")
    assert bucket_of_uuid(snap.message_id) == bucket_of(utcnow())


def test_unread_counts_others_messages_and_marks_forward_only() -> None:
    (svc, _, _, members, users, _, _, _, org_id, owner) = _service()
    member = _member(members, users, org_id)
    m1 = svc.send_message(org_id, owner, "one")
    svc.send_message(org_id, owner, "two")
    m3 = svc.send_message(org_id, owner, "three")
    assert svc.list_messages(org_id, member).unread == 3
    assert svc.list_messages(org_id, owner).unread == 0

    read = svc.mark_read(org_id, member, m3.message_id)
    assert read.last_read_message_id == m3.message_id
    assert svc.list_messages(org_id, member).unread == 0
    # A stale mark never drags the pointer backwards.
    stale = svc.mark_read(org_id, member, m1.message_id)
    assert stale.last_read_message_id == m3.message_id


def test_mark_read_rejects_ghost_message() -> None:
    svc, _, _, _, _, _, _, _, org_id, owner = _service()
    with pytest.raises(NotFoundError):
        svc.mark_read(org_id, owner, _uid())


def test_list_read_states_joins_member_briefs() -> None:
    """The group 'seen by' list exposes every member's pointer."""
    (svc, _, _, members, users, _, events, _, org_id,
     owner) = _service()
    member = _member(members, users, org_id)
    first = svc.send_message(org_id, owner, "one")
    second = svc.send_message(org_id, owner, "two")
    svc.mark_read(org_id, member, first.message_id)

    reads = svc.list_read_states(org_id, owner)
    by_id = {row.user_id: row for row in reads}
    # The author's pointer auto-advances on send; the member's stays
    # at the message they last marked.
    assert set(by_id) == {owner, member}
    assert by_id[owner].last_read_message_id == second.message_id
    assert by_id[member].last_read_message_id == first.message_id
    assert by_id[member].user_name == "Name mem@x.com"
    # A group mark fans out so every viewer repaints the receipts.
    assert any(c[1] == "message.read" for c in events.calls)


def test_list_read_states_denies_outsiders() -> None:
    svc, _, _, _, _, _, _, _, org_id, _ = _service()
    with pytest.raises(ForbiddenError):
        svc.list_read_states(org_id, _uid())


def test_delete_author_manager_and_denied_member() -> None:
    (svc, _, _, members, users, access, _, _, org_id,
     owner) = _service()
    member = _member(members, users, org_id)
    manager = _member(members, users, org_id, "mgr@x.com")
    access.perms[(org_id, manager)] = {"chat:manage"}
    snap = svc.send_message(org_id, owner, "x")
    with pytest.raises(ForbiddenError):
        svc.delete_message(org_id, member, snap.message_id)
    svc.delete_message(org_id, manager, snap.message_id)
    with pytest.raises(NotFoundError):
        svc.delete_message(org_id, owner, snap.message_id)
    own = svc.send_message(org_id, member, "mine")
    svc.delete_message(org_id, member, own.message_id)


def test_activity_room_members_chat_outsiders_denied() -> None:
    (svc, _, _, members, users, _,
     events, activities, org_id, owner) = _service()
    activity_id = _uid()
    activities.add(activity_id, org_id)
    member = _member(members, users, org_id)
    snap = svc.send_message(activity_id, member, "kickoff?")
    assert snap.room_id == activity_id
    page = svc.list_messages(activity_id, owner)
    assert [m.message_id for m in page.items] == [snap.message_id]
    outsider = _uid()
    users.add(outsider, "out@x.com", "Out")
    with pytest.raises(ForbiddenError):
        svc.list_messages(activity_id, outsider)
    # The event fans out on the room channel, not the org channel.
    assert events.calls[-1][0] == activity_id


def test_activity_room_unknown_id_is_not_found() -> None:
    svc, _, _, _, _, _, _, _, _, owner = _service()
    with pytest.raises(NotFoundError):
        svc.list_messages(_uid(), owner)


def test_open_dm_creates_converging_room() -> None:
    (svc, _, _, members, users, _, _, _, org_id,
     owner) = _service()
    peer = _member(members, users, org_id, "peer@x.com")
    room = svc.open_dm(org_id, owner, peer)
    again = svc.open_dm(org_id, peer, owner)
    assert again.room_id == room.room_id
    listed = svc.list_dm_rooms(org_id, peer)
    assert [r.room_id for r in listed] == [room.room_id]
    assert listed[0].peer_name == "Owner"


def test_open_dm_rejects_self_and_non_member_peer() -> None:
    (svc, _, _, members, users, _, _, _, org_id,
     owner) = _service()
    with pytest.raises(InvalidMemberStateError):
        svc.open_dm(org_id, owner, owner)
    stranger = _uid()
    users.add(stranger, "str@x.com", "Stranger")
    with pytest.raises(MemberNotFoundError):
        svc.open_dm(org_id, owner, stranger)
    with pytest.raises(ForbiddenError):
        svc.open_dm(org_id, stranger, owner)


def test_dm_room_isolates_messages_to_participants() -> None:
    (svc, _, _, members, users, _, _, _, org_id,
     owner) = _service()
    peer = _member(members, users, org_id, "peer@x.com")
    third = _member(members, users, org_id, "third@x.com")
    room = svc.open_dm(org_id, owner, peer)
    svc.send_message(room.room_id, peer, "secret")
    page = svc.list_messages(room.room_id, owner)
    assert [m.body for m in page.items] == ["secret"]
    assert svc.list_messages(room.room_id, peer).unread == 0
    # A third member of the same org cannot resolve the dm room at all.
    with pytest.raises(NotFoundError):
        svc.list_messages(room.room_id, third)


def test_can_access_mirrors_room_resolution() -> None:
    (svc, _, _, members, users, _, _, activities,
     org_id, owner) = _service()
    member = _member(members, users, org_id)
    activity_id = _uid()
    activities.add(activity_id, org_id)
    room = svc.open_dm(org_id, owner, member)
    assert svc.can_access(org_id, member)
    assert svc.can_access(activity_id, owner)
    assert svc.can_access(room.room_id, member)
    stranger = _uid()
    assert not svc.can_access(org_id, stranger)
    assert not svc.can_access(room.room_id, stranger)
    assert not svc.can_access(_uid(), member)


def test_message_carries_author_avatar_url() -> None:
    """Send and history both resolve the author's avatar asset URL."""
    media = FakeMedia()
    svc, _, _, _, users, _, _, _, org_id, owner = _service(media=media)
    face = media.create_asset(
        _uid(), owner, "users/u/a.png", "image/png", 10, utcnow(),
        role="avatar",
    )
    users.add(owner, "o@x.com", "Owner", avatar_media_id=face.asset_id)
    snap = svc.send_message(org_id, owner, "hi")
    assert snap.author_avatar_url == "/media/users/u/a.png"
    page = svc.list_messages(org_id, owner)
    assert page.items[0].author_avatar_url == "/media/users/u/a.png"


def test_message_ignores_dead_author_avatar_asset() -> None:
    """A dangling avatar_media_id yields null, never a broken URL."""
    svc, _, _, _, users, _, _, _, org_id, owner = _service(
        media=FakeMedia()
    )
    users.add(owner, "o@x.com", "Owner", avatar_media_id=_uid())
    snap = svc.send_message(org_id, owner, "hi")
    assert snap.author_avatar_url is None
