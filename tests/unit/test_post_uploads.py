"""Unit tests for board uploads (PostUploads) and PostMediaRules gating."""

from __future__ import annotations

import pytest

from core.exceptions import ForbiddenError, NotFoundError, UnsupportedMediaError
from core.media_rules import CHAT_OWNER, POST_OWNER
from posts.media_rules import PostMediaRules
from posts.uploads import PostUploads
from tests.unit.member_fakes import FakeAccess, FakeMembers, FakeOrgs, FakeUsers
from tests.unit.org_fakes import FakeMedia, FakeModeration, FakeStore
from tests.unit.workspace_fakes import NOW, _uid, add_org

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8


def _uploads_world():
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, media, store = FakeAccess(), FakeMedia(), FakeStore()
    moderation = FakeModeration()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    uploads = PostUploads(
        orgs, members, access, media, store, moderation=moderation
    )
    return uploads, org_id, owner, media, store, access, moderation, members


def test_member_upload_is_post_owned_and_outside_feed() -> None:
    uploads, org_id, owner, media, store, access, moderation, _ = (
        _uploads_world()
    )
    snap = uploads.upload(org_id, owner, "a.png", "image/png", PNG)

    row = media.get_asset(snap.id)
    assert row.owner_type == POST_OWNER
    assert row.owner_id == org_id
    assert snap.id not in {a.asset_id for a in media.list_gallery(org_id)}
    assert store.files[row.file_url] == PNG
    assert moderation.enqueued == [snap.id]
    assert ("post.upload", snap.id, "allowed") in access.audit
    assert snap.kind == "image"
    assert snap.org_id == org_id
    assert snap.original_name == "a.png"
    assert snap.file_url == f"/media/{row.file_url}"


def test_non_member_upload_forbidden() -> None:
    uploads, org_id, _, media, _, _, moderation, _ = _uploads_world()
    with pytest.raises(ForbiddenError):
        uploads.upload(org_id, _uid(), "a.png", "image/png", PNG)
    assert media.list_gallery(org_id) == []
    assert moderation.enqueued == []


def test_missing_org_is_not_found() -> None:
    uploads, _, owner, *_ = _uploads_world()
    with pytest.raises(NotFoundError):
        uploads.upload(_uid(), owner, "a.png", "image/png", PNG)


def test_unsupported_mime_rejected() -> None:
    uploads, org_id, owner, *_ = _uploads_world()
    with pytest.raises(UnsupportedMediaError):
        uploads.upload(org_id, owner, "a.txt", "text/plain", b"hi")


def _rules_world():
    media, store = FakeMedia(), FakeStore()
    org = _uid()
    return PostMediaRules(media, store), media, store, org


def test_rules_accept_post_owned_and_gallery_assets_of_same_org() -> None:
    rules, media, _, org = _rules_world()
    post = media.create_asset(
        _uid(), org, "orgs/o/p.png", "image/png", 4, NOW,
        role="attachment", owner_type=POST_OWNER, owner_feed=False,
    )
    gallery = media.create_asset(
        _uid(), org, "orgs/o/g.png", "image/png", 4, NOW, owner_type="organization")
    assert rules.attachments(org, [post.asset_id, gallery.asset_id]) == [
        post.asset_id,
        gallery.asset_id,
    ]


def test_rules_reject_chat_asset_even_in_same_org() -> None:
    rules, media, _, org = _rules_world()
    chat = media.create_asset(
        _uid(), org, "orgs/o/c.png", "image/png", 4, NOW,
        role="attachment", owner_type=CHAT_OWNER, owner_feed=False,
    )
    with pytest.raises(NotFoundError):
        rules.attachments(org, [chat.asset_id])


def test_rules_reject_other_org_post_asset() -> None:
    rules, media, _, org = _rules_world()
    foreign = media.create_asset(
        _uid(), _uid(), "orgs/x/p.png", "image/png", 4, NOW,
        role="attachment", owner_type=POST_OWNER, owner_feed=False,
    )
    with pytest.raises(NotFoundError):
        rules.attachments(org, [foreign.asset_id])


def test_rules_reject_legacy_org_attachment_row() -> None:
    rules, media, _, org = _rules_world()
    legacy = media.create_asset(
        _uid(), org, "orgs/o/l.png", "image/png", 4, NOW,
        role="attachment", owner_type="organization")
    with pytest.raises(NotFoundError):
        rules.attachments(org, [legacy.asset_id])


def test_rules_reject_rejected_status() -> None:
    rules, media, _, org = _rules_world()
    post = media.create_asset(
        _uid(), org, "orgs/o/p.png", "image/png", 4, NOW,
        role="attachment", owner_type=POST_OWNER, owner_feed=False,
    )
    media.set_upload_status(post.asset_id, "rejected")
    with pytest.raises(NotFoundError):
        rules.attachments(org, [post.asset_id])


def test_purge_deletes_only_post_owned_rows_of_the_org() -> None:
    rules, media, store, org = _rules_world()
    post = media.create_asset(
        _uid(), org, "orgs/o/p.png", "image/png", 4, NOW,
        role="attachment", owner_type=POST_OWNER, owner_feed=False,
    )
    chat = media.create_asset(
        _uid(), org, "orgs/o/c.png", "image/png", 4, NOW,
        role="attachment", owner_type=CHAT_OWNER, owner_feed=False,
    )
    gallery = media.create_asset(
        _uid(), org, "orgs/o/g.png", "image/png", 4, NOW, owner_type="organization")
    for row in (post, chat, gallery):
        store.files[row.file_url] = b"1"

    removed = rules.purge_attachments(
        org, [post.asset_id, chat.asset_id, gallery.asset_id]
    )

    assert removed == 1
    assert media.get_asset(post.asset_id) is None
    assert post.file_url not in store.files
    assert media.get_asset(chat.asset_id) is not None
    assert media.get_asset(gallery.asset_id) is not None
