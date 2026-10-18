"""Unit tests for ChatAttachments: staging, claims, resolving, discarding."""

from __future__ import annotations

import pytest

from chat.attachments import ChatAttachments
from chat.dtos import AttachmentBrief
from core.exceptions import ForbiddenError, NotFoundError
from core.media_rules import CHAT_OWNER, POST_OWNER
from tests.unit.chat_fakes import FakeChatStore
from tests.unit.org_fakes import FakeMedia, FakeModeration, FakeStore
from tests.unit.workspace_fakes import NOW, _uid

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8


def _world():
    media, store, moderation = FakeMedia(), FakeStore(), FakeModeration()
    chat = FakeChatStore()
    attachments = ChatAttachments(media, store, chat, moderation=moderation)
    return attachments, media, store, chat, moderation


def test_stage_creates_chat_owned_row_outside_gallery_feed() -> None:
    attachments, media, store, _, moderation = _world()
    org, room, actor = _uid(), _uid(), _uid()
    brief = attachments.stage(org, room, actor, "a.png", "image/png", PNG)

    row = media.get_asset(brief.media_id)
    assert row.owner_type == CHAT_OWNER
    assert row.owner_id == room
    assert row.role == "attachment"
    assert row.uploader_id == actor
    assert brief.media_id not in {a.asset_id for a in media.list_gallery(org)}
    assert brief.media_id not in {a.asset_id for a in media.list_gallery(room)}
    assert brief.url == f"/media/{row.file_url}"
    assert brief.name == "a.png"
    assert brief.size_bytes == len(PNG)
    assert row.file_url.startswith(f"orgs/{org}/")
    assert store.files[row.file_url] == PNG
    assert moderation.enqueued == [brief.media_id]


def test_resolve_claims_for_one_message() -> None:
    attachments, _, _, chat, _ = _world()
    org, room, actor = _uid(), _uid(), _uid()
    brief = attachments.stage(org, room, actor, "a.png", "image/png", PNG)

    message_id = _uid()
    resolved = attachments.resolve(room, actor, [brief.media_id], message_id)

    assert resolved == [
        AttachmentBrief(
            media_id=brief.media_id,
            url=brief.url,
            mime="image/png",
            name="a.png",
            size_bytes=len(PNG),
        )
    ]
    claim = chat.claimed_attachment(brief.media_id)
    assert claim is not None and claim.message_id == message_id


def test_resolve_rejects_a_file_already_sent() -> None:
    """One file may attach to exactly one message (regression: shared bytes)."""
    attachments, _, _, _, _ = _world()
    org, room, actor = _uid(), _uid(), _uid()
    brief = attachments.stage(org, room, actor, "a.png", "image/png", PNG)

    attachments.resolve(room, actor, [brief.media_id], _uid())
    with pytest.raises(ForbiddenError):
        attachments.resolve(room, actor, [brief.media_id], _uid())


def test_resolve_rolls_back_claims_when_a_later_id_fails() -> None:
    attachments, _, _, chat, _ = _world()
    org, room, actor = _uid(), _uid(), _uid()
    first = attachments.stage(org, room, actor, "1.png", "image/png", PNG)

    with pytest.raises(NotFoundError):
        attachments.resolve(room, actor, [first.media_id, _uid()], _uid())
    assert chat.claimed_attachment(first.media_id) is None


def test_resolve_rejects_other_room_and_other_uploader() -> None:
    attachments, _, _, _, _ = _world()
    org, room, actor = _uid(), _uid(), _uid()
    brief = attachments.stage(org, room, actor, "a.png", "image/png", PNG)
    with pytest.raises(ForbiddenError):
        attachments.resolve(_uid(), actor, [brief.media_id], _uid())
    with pytest.raises(ForbiddenError):
        attachments.resolve(room, _uid(), [brief.media_id], _uid())


def test_resolve_rejects_gallery_and_post_assets() -> None:
    attachments, media, _, _, _ = _world()
    org, actor = _uid(), _uid()
    gallery = media.create_asset(
        _uid(), org, "orgs/o/g.png", "image/png", 4, NOW,
        role="gallery", uploader_id=actor, owner_type="organization",
    )
    post = media.create_asset(
        _uid(), org, "orgs/o/p.png", "image/png", 4, NOW,
        role="attachment", uploader_id=actor, owner_type=POST_OWNER,
        owner_feed=False,
    )
    with pytest.raises(ForbiddenError):
        attachments.resolve(org, actor, [gallery.asset_id], _uid())
    with pytest.raises(ForbiddenError):
        attachments.resolve(org, actor, [post.asset_id], _uid())


def test_resolve_missing_asset_is_not_found() -> None:
    attachments, _, _, _, _ = _world()
    with pytest.raises(NotFoundError):
        attachments.resolve(_uid(), _uid(), [_uid()], _uid())


def test_discard_staged_removes_unsent_file() -> None:
    attachments, media, store, _, _ = _world()
    org, room, actor = _uid(), _uid(), _uid()
    brief = attachments.stage(org, room, actor, "a.png", "image/png", PNG)

    attachments.discard_staged(room, actor, brief.media_id)

    assert media.get_asset(brief.media_id) is None
    assert store.files == {}


def test_discard_staged_rejects_claimed_other_room_other_uploader() -> None:
    attachments, _, _, _, _ = _world()
    org, room, actor = _uid(), _uid(), _uid()
    brief = attachments.stage(org, room, actor, "a.png", "image/png", PNG)

    attachments.resolve(room, actor, [brief.media_id], _uid())
    with pytest.raises(ForbiddenError):
        attachments.discard_staged(room, actor, brief.media_id)
    with pytest.raises(ForbiddenError):
        attachments.discard_staged(_uid(), actor, brief.media_id)
    with pytest.raises(ForbiddenError):
        attachments.discard_staged(room, _uid(), brief.media_id)


def test_discard_removes_only_this_rooms_chat_files() -> None:
    attachments, media, store, chat, _ = _world()
    org, actor = _uid(), _uid()
    room_a, room_b = _uid(), _uid()
    first = attachments.stage(org, room_a, actor, "1.png", "image/png", PNG)
    second = attachments.stage(org, room_a, actor, "2.png", "image/png", PNG)
    other = attachments.stage(org, room_b, actor, "3.png", "image/png", PNG)
    other_path = media.get_asset(other.media_id).file_url
    message_id = _uid()
    attachments.resolve(
        room_a, actor, [first.media_id, second.media_id], message_id
    )

    removed = attachments.discard(room_a, [first, second, other])

    assert removed == 2
    assert media.get_asset(first.media_id) is None
    assert media.get_asset(second.media_id) is None
    assert media.get_asset(other.media_id) is not None
    assert other_path in store.files
    assert len(store.files) == 1
    assert chat.claims == {}
