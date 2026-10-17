"""Unit tests for ChatInboxService: cross-org rows, preview, unread."""

from __future__ import annotations

from uuid import UUID

from chat.composer import ChatComposer
from chat.helpers import bucket_of
from chat.inbox_service import ChatInboxService
from chat.service import ChatService
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


def _world():
    chat = FakeChatStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, events = FakeAccess(), FakeChatEvents()
    activities = FakeActivities()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    svc = ChatService(
        chat, orgs, members, users, access, events, activities,
        composer=ChatComposer(
            chat, orgs, members, users, access, events,
            FakeMedia(), FakeUploader(), activities,
        ),
    )
    inbox = ChatInboxService(chat, orgs, members, users, activities)
    return svc, inbox, chat, orgs, members, users, events, activities, org_id, owner


def _member(
    members: FakeMembers, users: FakeUsers, org_id: UUID,
    email: str = "mem@x.com",
) -> UUID:
    uid = _uid()
    users.add(uid, email, f"Name {email}")
    members.put(org_id, uid, "active", NOW)
    return uid


def test_inbox_merges_general_activity_and_dm_rooms() -> None:
    (svc, inbox, _, _, members, users,
     _, activities, org_id, owner) = _world()
    peer = _member(members, users, org_id, "peer@x.com")
    activity_id = _uid()
    activities.add(activity_id, org_id, title="Workshop")
    dm = svc.open_dm(org_id, owner, peer)
    rows = {row.room_id: row for row in inbox.list_inbox(owner)}
    assert {row.kind for row in rows.values()} == {
        "general", "activity", "dm"
    }
    assert rows[org_id].title == "Org"
    assert rows[activity_id].title == "Workshop"
    assert rows[dm.room_id].title == "Name peer@x.com"
    assert rows[dm.room_id].peer_id == peer


def test_inbox_sorted_by_latest_message_then_creation() -> None:
    (svc, inbox, _, orgs, members, users,
     _, _, org_id, owner) = _world()
    other_owner = _uid()
    users.add(other_owner, "o2@x.com", "Owner2")
    second_org = add_org(orgs, members, users, other_owner, "Second")
    # Owner also belongs to the second org so its room enters the inbox.
    members.put(second_org, owner, "active", NOW)
    svc.send_message(org_id, owner, "fresh")
    rows = inbox.list_inbox(owner)
    assert rows[0].room_id == org_id
    assert rows[0].last_body == "fresh"
    assert rows[0].last_author_name == "Owner"
    assert rows[1].room_id == second_org
    assert rows[1].last_body is None
    assert rows[0].sort_at >= rows[1].sort_at


def test_inbox_unread_counts_others_messages_only() -> None:
    (svc, inbox, _, _, members, users, _, _, org_id, owner) = _world()
    member = _member(members, users, org_id)
    svc.send_message(org_id, member, "hello owner")
    svc.send_message(org_id, member, "again")
    rows = {row.room_id: row for row in inbox.list_inbox(owner)}
    assert rows[org_id].unread == 2
    rows = {row.room_id: row for row in inbox.list_inbox(member)}
    assert rows[org_id].unread == 0  # the sender's own sends stay read


def test_inbox_skips_orgs_the_user_left() -> None:
    (svc, inbox, _, orgs, members, users, _, _, org_id, owner) = _world()
    peer = _member(members, users, org_id, "peer@x.com")
    dm = svc.open_dm(org_id, owner, peer)
    members.set_status(org_id, peer, "left", NOW)
    orgs.orgs[org_id].deleted_at = utcnow()  # even a tombstoned org is out
    rows = inbox.list_inbox(peer)
    assert all(row.org_id != org_id for row in rows)
    # The dm room dies with the org membership, matching _open_room.
    assert all(row.room_id != dm.room_id for row in rows)


def test_send_and_dm_open_emit_inbox_hints() -> None:
    (svc, _, _, _, members, users, events, _, org_id, owner) = _world()
    peer = _member(members, users, org_id, "peer@x.com")
    svc.send_message(org_id, owner, "hi")
    action, room_id, event_org, peers = events.inbox[-1]
    assert action == "message.created"
    assert room_id == org_id and event_org == org_id and peers == ()
    dm = svc.open_dm(org_id, owner, peer)
    action, room_id, event_org, peers = events.inbox[-1]
    assert action == "dm.opened"
    assert room_id == dm.room_id and event_org == org_id
    assert set(peers) == {owner, peer}
    svc.send_message(dm.room_id, owner, "secret")
    action, room_id, _, peers = events.inbox[-1]
    assert action == "message.created"
    assert room_id == dm.room_id
    assert set(peers) == {owner, peer}


def test_inbox_preview_truncates_long_bodies() -> None:
    (svc, inbox, _, _, _, _, _, _, org_id, owner) = _world()
    svc.send_message(org_id, owner, "x" * 500)
    row = inbox.list_inbox(owner)[0]
    assert row.last_body is not None and len(row.last_body) == 160
    assert row.last_at is not None
    assert bucket_of(row.last_at) == bucket_of(utcnow())


def test_inbox_rows_carry_org_logo_and_peer_avatar() -> None:
    """Group rows surface the org logo; dm rows the peer avatar."""
    chat, orgs, members = FakeChatStore(), FakeOrgs(), FakeMembers()
    users, activities, media = FakeUsers(), FakeActivities(), FakeMedia()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    peer = _member(members, users, org_id, "peer@x.com")
    logo = media.create_asset(
        _uid(), org_id, "orgs/x/logo.png", "image/png", 10, NOW
    )
    orgs.orgs[org_id].logo_media_id = logo.asset_id
    face = media.create_asset(
        _uid(), org_id, "users/p/a.png", "image/png", 10, NOW
    )
    users.add(peer, "peer@x.com", "Peer", avatar_media_id=face.asset_id)
    act_id = _uid()
    activities.add(act_id, org_id, title="Workshop")
    svc = ChatService(
        chat, orgs, members, users, FakeAccess(), FakeChatEvents(),
        activities,
    )
    dm = svc.open_dm(org_id, owner, peer)
    inbox = ChatInboxService(
        chat, orgs, members, users, activities, media
    )
    rows = {row.room_id: row for row in inbox.list_inbox(owner)}
    assert rows[org_id].avatar_url == "/media/orgs/x/logo.png"
    assert rows[act_id].avatar_url == "/media/orgs/x/logo.png"
    assert rows[dm.room_id].avatar_url == "/media/users/p/a.png"
