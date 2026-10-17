"""Unit tests for the org_room_media shared-item index and its service."""

from __future__ import annotations

import pytest

from chat.crypto import ChatCipher
from chat.dtos import AttachmentBrief
from chat.helpers import (
    MAX_LINKS_PER_MESSAGE,
    build_index_items,
    extract_links,
    media_kind_of,
)
from chat.media_service import ChatMediaService
from chat.service import ChatService
from core.exceptions import ForbiddenError
from chat.composer import ChatComposer
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

KEY = b"0" * 32  # AES-256 test key


def _attachment(mime: str = "image/png", name: str = "a.png"):
    return AttachmentBrief(
        media_id=_uid(),
        url="/media/x/a.png",
        mime=mime,
        name=name,
        size_bytes=10,
    )


def _stack():
    """Composer + media service over the same in-memory stores."""
    chat = FakeChatStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, events = FakeAccess(), FakeChatEvents()
    activities = FakeActivities()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    cipher = ChatCipher(KEY)
    composer = ChatComposer(
        chat, orgs, members, users, access, events,
        FakeMedia(), FakeUploader(), activities, cipher=cipher,
    )
    service = ChatService(
        chat, orgs, members, users, access, events, activities,
        cipher=cipher, composer=composer,
    )
    media_svc = ChatMediaService(
        chat=chat, orgs=orgs, members=members, users=users,
        access=access, activities=activities, cipher=cipher,
    )
    return service, media_svc, chat, org_id, owner, members, users


def test_media_kind_of_buckets_by_mime() -> None:
    assert media_kind_of("image/png") == "image"
    assert media_kind_of("video/mp4") == "video"
    assert media_kind_of("application/pdf") == "file"
    assert media_kind_of("") == "file"


def test_extract_links_dedupes_strips_and_caps() -> None:
    text = (
        "see https://a.example/x, https://a.example/x again "
        "and http://b.example/y). also https://c.example/z."
    )
    assert extract_links(text) == [
        "https://a.example/x",
        "http://b.example/y",
        "https://c.example/z",
    ]
    many = " ".join(f"https://e{i}.example/" for i in range(20))
    assert len(extract_links(many)) == MAX_LINKS_PER_MESSAGE


def test_build_index_items_kinds_and_link_encryption() -> None:
    cipher = ChatCipher(KEY)
    items = build_index_items(
        [
            _attachment("image/jpeg"),
            _attachment("video/mp4"),
            _attachment("application/pdf"),
        ],
        "https://link.example/doc",
        cipher,
    )
    assert [i.kind for i in items] == ["image", "video", "file", "link"]
    assert [i.item_index for i in items] == [0, 0, 0, 0]
    link = items[-1]
    assert link.url.startswith("v1gcm:")
    assert cipher.decrypt(link.url) == "https://link.example/doc"


def test_send_indexes_attachments_and_links() -> None:
    svc, media_svc, chat, org_id, owner, *_ = _stack()
    svc.send_message(org_id, owner, "pic + https://ex.com/a")
    # Attachment ids resolve through the uploader only; a bare link is
    # enough to prove the write path without staging media assets.
    rows = [r for r in chat.media if r.room_id == org_id]
    assert len(rows) == 1
    assert rows[0].kind == "link"
    assert rows[0].url.startswith("v1gcm:")
    page = media_svc.list_shared_media(org_id, owner, kind="link")
    assert len(page.items) == 1
    assert page.items[0].url == "https://ex.com/a"
    assert page.items[0].author_name == "Owner"


def test_edit_reindexes_links_but_keeps_attachments() -> None:
    svc, media_svc, chat, org_id, owner, *_ = _stack()
    sent = svc.send_message(org_id, owner, "see https://old.example")
    svc.edit_message(org_id, owner, sent.message_id, "see https://new.example")
    links = [r for r in chat.media if r.kind == "link"]
    assert len(links) == 1
    page = media_svc.list_shared_media(org_id, owner, kind="link")
    assert page.items[0].url == "https://new.example"


def test_delete_message_drops_its_index_rows() -> None:
    svc, media_svc, chat, org_id, owner, *_ = _stack()
    sent = svc.send_message(org_id, owner, "see https://old.example")
    svc.delete_message(org_id, owner, sent.message_id)
    assert [r for r in chat.media if r.message_id == sent.message_id] == []
    page = media_svc.list_shared_media(org_id, owner, kind="link")
    assert page.items == []


def test_media_list_requires_membership() -> None:
    _svc, media_svc, _chat, org_id, _owner, *_ = _stack()
    with pytest.raises(ForbiddenError):
        media_svc.list_shared_media(org_id, _uid(), kind="image")


def test_media_pages_walk_newest_first() -> None:
    svc, media_svc, _chat, org_id, owner, *_ = _stack()
    for i in range(5):
        svc.send_message(org_id, owner, f"https://ex.com/{i}")
    first = media_svc.list_shared_media(org_id, owner, kind="link", limit=3)
    assert [i.url for i in first.items] == [
        "https://ex.com/4", "https://ex.com/3", "https://ex.com/2"
    ]
    second = media_svc.list_shared_media(
        org_id, owner, kind="link", limit=3, cursor=first.next_cursor
    )
    assert [i.url for i in second.items] == [
        "https://ex.com/1", "https://ex.com/0"
    ]
    assert second.next_cursor is None


def test_media_rows_carry_author_attribution() -> None:
    svc, media_svc, _chat, org_id, owner, *_ = _stack()
    svc.send_message(org_id, owner, "https://ex.com/only")
    page = media_svc.list_shared_media(org_id, owner, kind="link")
    item = page.items[0]
    assert item.author_id == owner
    assert item.created_at is not None
    assert item.kind == "link"


def _second_member(members, users, org_id, name="Member"):  # noqa: ANN001, ANN201
    peer = _uid()
    members.put(org_id, peer, "active", NOW)
    users.add(peer, f"{name.lower()}@example.com", name)
    return peer


def test_media_author_filter_narrows_to_one_sender() -> None:
    svc, media_svc, _c, org_id, owner, members, users = _stack()
    peer = _second_member(members, users, org_id)
    svc.send_message(org_id, owner, "mine https://ex.com/owner")
    svc.send_message(org_id, peer, "theirs https://ex.com/peer")

    page = media_svc.list_shared_media(
        org_id, owner, kind="link", author_id=peer
    )
    assert [i.url for i in page.items] == ["https://ex.com/peer"]
    assert page.items[0].author_name == "Member"

    everything = media_svc.list_shared_media(org_id, owner, kind="link")
    assert {i.url for i in everything.items} == {
        "https://ex.com/owner",
        "https://ex.com/peer",
    }


def test_media_authors_list_once_per_sender() -> None:
    svc, media_svc, _c, org_id, owner, members, users = _stack()
    peer = _second_member(members, users, org_id)
    svc.send_message(org_id, owner, "https://ex.com/one https://ex.com/two")
    svc.send_message(org_id, peer, "https://ex.com/peer")

    authors = media_svc.list_media_authors(org_id, owner)
    assert [a.author_name for a in authors] == ["Member", "Owner"]
    assert set(authors[0].kinds) == {"link"}
    assert set(authors[1].kinds) == {"link"}


def test_media_author_presence_pruned_after_last_item_deleted() -> None:
    svc, media_svc, _c, org_id, owner, members, users = _stack()
    peer = _second_member(members, users, org_id)
    svc.send_message(org_id, owner, "https://ex.com/owner")
    sent = svc.send_message(org_id, peer, "https://ex.com/peer")

    svc.delete_message(org_id, peer, sent.message_id)
    authors = media_svc.list_media_authors(org_id, owner)
    assert [a.author_id for a in authors] == [owner]
    filtered = media_svc.list_shared_media(
        org_id, owner, kind="link", author_id=peer
    )
    assert filtered.items == []


def test_media_authors_requires_membership() -> None:
    _svc, media_svc, _chat, org_id, _owner, *_ = _stack()
    with pytest.raises(ForbiddenError):
        media_svc.list_media_authors(org_id, _uid())
