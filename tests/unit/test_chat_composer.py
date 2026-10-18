"""Unit tests for ChatComposer: reply metadata, edits, attachments."""

from __future__ import annotations

import pytest

from chat.attachments import ChatAttachments
from chat.composer import ChatComposer
from chat.service import ChatService
from core.exceptions import (
    ChatContentRequiredError,
    ForbiddenError,
    NotFoundError,
)
from tests.unit.member_fakes import (
    FakeAccess,
    FakeMembers,
    FakeOrgs,
    FakeUsers,
)
from tests.unit.org_fakes import FakeMedia, FakeStore
from tests.unit.channel_fakes import FakeChannelStore
from tests.unit.chat_fakes import (
    FakeActivities,
    FakeChatEvents,
    FakeChatStore,
)
from tests.unit.workspace_fakes import (
    NOW,
    _uid,
    add_org,
)


def _world(store: FakeStore | None = None):
    chat = FakeChatStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, events = FakeAccess(), FakeChatEvents()
    activities = FakeActivities()
    media = FakeMedia()
    attachments = ChatAttachments(
        media, store if store is not None else FakeStore(), chat
    )
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    composer = ChatComposer(
        chat, orgs, members, users, access, events,
        media, attachments, activities,
    )
    svc = ChatService(
        chat, orgs, members, users, access, events, activities,
        composer=composer, attachments=attachments,
    )
    return (
        svc, chat, orgs, members, users, access, events,
        media, attachments, org_id, owner,
    )


def _member(members, users, org_id, email="mem@x.com"):  # noqa: ANN001, ANN202
    uid = _uid()
    users.add(uid, email, f"Name {email}")
    members.put(org_id, uid, "active", NOW)
    return uid


def test_send_without_content_rejected() -> None:
    svc, *_rest, org_id, owner = _world()
    with pytest.raises(ChatContentRequiredError):
        svc.send_message(org_id, owner, "   ")


def test_reply_denormalizes_author_and_snippet() -> None:
    (svc, _, _, members, users, _, _,
     _, _, org_id, owner) = _world()
    target = svc.send_message(org_id, owner, "x" * 200)
    member = _member(members, users, org_id)
    reply = svc.send_message(
        org_id, member, "\u0111\u1ED3ng \u00FD", reply_to_id=target.message_id
    )
    assert reply.reply_to_id == target.message_id
    assert reply.reply_to_author == users.get_brief(owner).full_name
    assert len(reply.reply_to_body or "") <= 140
    page = svc.list_messages(org_id, owner)
    stored = next(m for m in page.items if m.message_id == reply.message_id)
    assert stored.reply_to_body == "x" * 140


def test_reply_to_missing_message_404() -> None:
    svc, *_rest, org_id, owner = _world()
    with pytest.raises(NotFoundError):
        svc.send_message(org_id, owner, "hi", reply_to_id=_uid())


def test_edit_by_author_sets_edited_at() -> None:
    svc, _, _, _, _, _, events, _, _, org_id, owner = _world()
    snap = svc.send_message(org_id, owner, "g\u1ED1c")
    edited = svc.edit_message(org_id, owner, snap.message_id, "\u0111\u00E3 s\u1EEDa")
    assert edited.body == "\u0111\u00E3 s\u1EEDa"
    assert edited.edited_at is not None
    assert (org_id, "message.edited") in [
        (r, a) for r, a, *_ in events.calls
    ]


def test_edit_by_non_author_denied() -> None:
    (svc, _, _, members, users, access,
     _, _, _, org_id, owner) = _world()
    snap = svc.send_message(org_id, owner, "g\u1ED1c")
    member = _member(members, users, org_id)
    with pytest.raises(ForbiddenError):
        svc.edit_message(org_id, member, snap.message_id, "chi\u1EBFm")
    assert ("chat.edit", snap.message_id, "denied") in access.audit


def test_attachment_flow_embeds_brief() -> None:
    (svc, _, _, _, _, _, _,
     media, _, org_id, owner) = _world()
    brief = svc.create_attachment(
        org_id, owner, "a.png", "image/png", b"\x89png"
    )
    staged = media.get_asset(brief.media_id)
    assert staged.owner_type == "chat"
    assert staged.owner_id == org_id
    assert staged.role == "attachment"
    snap = svc.send_message(
        org_id, owner, "", attachment_ids=[brief.media_id]
    )
    assert len(snap.attachments) == 1
    assert snap.attachments[0].mime == "image/png"
    assert snap.attachments[0].url.startswith("/media/")


def test_attachment_from_another_room_rejected() -> None:
    (svc, _, orgs, members, users, _,
     _, media, _, org_id, owner) = _world()
    other_owner = _uid()
    other_org = add_org(orgs, members, users, other_owner, "Other")
    foreign = media.create_asset(
        _uid(), other_org, "orgs/o/x.png", "image/png", 4, NOW,
        role="attachment", uploader_id=owner, owner_type="chat",
        owner_feed=False,
    )
    with pytest.raises(ForbiddenError):
        svc.send_message(org_id, owner, "", attachment_ids=[foreign.asset_id])


def test_attachment_missing_404_and_gallery_asset_denied() -> None:
    svc, *_rest, media, _attachments, org_id, owner = _world()
    with pytest.raises(NotFoundError):
        svc.send_message(org_id, owner, "", attachment_ids=[_uid()])
    gallery = media.create_asset(
        _uid(), org_id, "orgs/o/g.png", "image/png", 4, NOW,
        role="gallery", uploader_id=owner, owner_type="organization")
    with pytest.raises(ForbiddenError):
        svc.send_message(org_id, owner, "", attachment_ids=[gallery.asset_id])


def test_mentions_skip_restricted_channel_outsiders() -> None:
    """@name inside a restricted channel never notifies non-readers."""
    chat = FakeChatStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, events = FakeAccess(), FakeChatEvents()
    media, channels = FakeMedia(), FakeChannelStore()
    attachments = ChatAttachments(media, FakeStore(), chat)
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    insider = _member(members, users, org_id, "in@x.com")
    outsider = _member(members, users, org_id, "out@x.com")
    channel = channels.create_channel(
        org_id, "Private", "", "channel", "everyone", "restricted",
        owner, NOW,
    )
    channels.add_channel_member(
        channel.channel_id, org_id, insider, owner, NOW
    )
    composer = ChatComposer(
        chat, orgs, members, users, access, events,
        media, attachments, FakeActivities(), channels=channels,
    )
    svc = ChatService(
        chat, orgs, members, users, access, events, FakeActivities(),
        composer=composer, attachments=attachments, channels=channels,
    )

    outsider_name = users.get_brief(outsider).full_name
    snap = svc.send_message(
        channel.channel_id, insider, f"hi @{outsider_name}"
    )
    assert not snap.mentions

    owner_name = users.get_brief(owner).full_name
    snap2 = svc.send_message(
        channel.channel_id, insider, f"hi @{owner_name}"
    )
    assert [m.user_id for m in snap2.mentions] == [owner]


def test_delete_message_discards_its_files() -> None:
    store = FakeStore()
    (svc, _, _, _, _, _, _,
     media, _, org_id, owner) = _world(store)
    brief = svc.create_attachment(
        org_id, owner, "a.png", "image/png", b"\x89png"
    )
    snap = svc.send_message(
        org_id, owner, "", attachment_ids=[brief.media_id]
    )
    assert brief.url[len("/media/"):] in store.files
    svc.delete_message(org_id, owner, snap.message_id)
    assert media.get_asset(brief.media_id) is None
    assert brief.url[len("/media/"):] not in store.files
