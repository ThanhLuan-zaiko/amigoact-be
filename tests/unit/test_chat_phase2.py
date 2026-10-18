"""Unit tests for chat phase 2: reactions, receipts, mentions, crypto."""

from __future__ import annotations

import pytest

from chat.composer import ChatComposer
from chat.crypto import ChatCipher
from chat.service import ChatService
from core.exceptions import InvalidMemberStateError
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
    FakeNotify,
    _uid,
    add_org,
)


def _world(cipher=True):
    chat = FakeChatStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, events = FakeAccess(), FakeChatEvents()
    activities = FakeActivities()
    notify = FakeNotify()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    c = ChatCipher(b"\x01" * 32) if cipher else None
    composer = ChatComposer(
        chat, orgs, members, users, access, events,
        FakeMedia(), make_attachments(), activities,
        cipher=c, notifications=notify,
    )
    svc = ChatService(
        chat, orgs, members, users, access, events, activities,
        composer=composer, cipher=c,
    )
    return svc, chat, orgs, members, users, events, notify, org_id, owner


def _member(members, users, org_id, name="Mem One"):
    uid = _uid()
    users.add(uid, f"{uid.hex[:8]}@x.com", name)
    members.put(org_id, uid, "active", NOW)
    return uid


def test_bodies_encrypted_at_rest():
    svc, chat, *_x, org_id, owner = _world()
    sent = svc.send_message(org_id, owner, "hello secret")
    row = chat.messages[-1]
    assert row.body.startswith("v1gcm:")
    assert sent.body == "hello secret"
    reply = svc.send_message(
        org_id, owner, "quoted", reply_to_id=sent.message_id
    )
    assert chat.messages[-1].reply_to_body.startswith("v1gcm:")
    assert reply.reply_to_body == "hello secret"


def test_edit_reencrypts_body():
    svc, chat, *_x, org_id, owner = _world()
    sent = svc.send_message(org_id, owner, "first")
    svc.edit_message(org_id, owner, sent.message_id, "second")
    assert chat.messages[-1].body.startswith("v1gcm:")
    page = svc.list_messages(org_id, owner)
    assert page.items[-1].body == "second"


def test_reaction_toggle_tallies():
    svc, _c, _o, _m, _u, events, _n, org_id, owner = _world()
    sent = svc.send_message(org_id, owner, "hi")
    out = svc.toggle_reaction(org_id, owner, sent.message_id, "\U0001F44D")
    assert out.reactions == (
        out.reactions[0].__class__(emoji="\U0001F44D", count=1, mine=True),
    )
    again = svc.toggle_reaction(org_id, owner, sent.message_id, "\U0001F44D")
    assert again.reactions == ()
    assert any(c[1] == "message.reacted" for c in events.calls)


def test_reaction_rejects_unknown_emoji():
    svc, _c, _o, _m, _u, _e, _n, org_id, owner = _world()
    sent = svc.send_message(org_id, owner, "hi")
    with pytest.raises(InvalidMemberStateError):
        svc.toggle_reaction(org_id, owner, sent.message_id, "\U0001F984")


def test_dm_read_receipt_visible_to_sender():
    svc, chat, orgs, members, users, _e, _n, org_id, owner = _world()
    peer = _member(members, users, org_id)
    room = svc.open_dm(org_id, owner, peer)
    sent = svc.send_message(room.room_id, owner, "dm hi")
    svc.mark_read(room.room_id, peer, sent.message_id)
    page = svc.list_messages(room.room_id, owner)
    assert page.peer_last_read_message_id == sent.message_id
    # Group rooms never expose other members' read pointers.
    group = svc.list_messages(org_id, owner)
    assert group.peer_last_read_message_id is None


def test_mention_notifies_and_persists():
    svc, chat, orgs, members, users, _e, notify, org_id, owner = _world()
    peer = _member(members, users, org_id, name="Mem One")
    sent = svc.send_message(org_id, owner, "hi @Mem One check this")
    assert [m.user_id for m in sent.mentions] == [peer]
    kinds = [c[1] for c in notify.calls]
    assert kinds == ["chat.mention"]
    assert chat.messages[-1].mentions_json is not None


def test_no_mentions_inside_dm():
    svc, _c, orgs, members, users, _e, notify, org_id, owner = _world()
    peer = _member(members, users, org_id, name="Mem One")
    room = svc.open_dm(org_id, owner, peer)
    sent = svc.send_message(room.room_id, owner, "hi @Mem One")
    assert sent.mentions == ()
    assert notify.calls == []


def test_pin_requires_manager_and_collects_many():
    svc, chat, orgs, members, users, events, _n, org_id, owner = _world()
    sent = svc.send_message(org_id, owner, "pin me")
    second = svc.send_message(org_id, owner, "pin me too")
    member = _member(members, users, org_id)
    with pytest.raises(Exception):
        svc.pin_message(org_id, member, sent.message_id)
    svc.pin_message(org_id, owner, sent.message_id)
    svc.pin_message(org_id, owner, second.message_id)
    page = svc.list_messages(org_id, owner)
    assert [p.message_id for p in page.pinned] == [
        sent.message_id, second.message_id
    ]
    assert any(c[1] == "message.pinned" for c in events.calls)
    svc.unpin_message(org_id, owner, sent.message_id)
    page = svc.list_messages(org_id, owner)
    assert [p.message_id for p in page.pinned] == [second.message_id]
    svc.unpin_message(org_id, owner, second.message_id)
    assert svc.list_messages(org_id, owner).pinned == []


def test_delete_clears_pin_and_mute_flags():
    svc, chat, orgs, members, users, _e, _n, org_id, owner = _world()
    sent = svc.send_message(org_id, owner, "pin me")
    svc.pin_message(org_id, owner, sent.message_id)
    svc.delete_message(org_id, owner, sent.message_id)
    assert svc.list_messages(org_id, owner).pinned == []
    svc.set_mute(org_id, owner, True)
    assert svc.list_messages(org_id, owner).muted is True
    svc.set_mute(org_id, owner, False)
    assert svc.list_messages(org_id, owner).muted is False
