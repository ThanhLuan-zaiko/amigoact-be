"""Unit tests for MediaService branding rules (fake ports, no I/O)."""

from __future__ import annotations

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidMediaRoleError,
    MediaTooLargeError,
    NotFoundError,
    UnsupportedMediaError,
)
from tests.unit.org_fakes import make_media_services, new_owner


def test_brand_media_ids_follow_roles_and_delete() -> None:
    orgs_service, service, orgs, _, _ = make_media_services()
    owner = new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")

    cover = service.upload_media(
        org.id, owner, "a.png", "image/png", b"1" * 10, "cover"
    )
    assert orgs.get_by_id(org.id).cover_media_id == cover.id
    assert cover.uploader_id == owner
    assert cover.original_name == "a.png"

    # Switching back to gallery clears the brand pointer.
    service.set_media_role(org.id, owner, cover.id, "gallery")
    assert orgs.get_by_id(org.id).cover_media_id is None

    service.set_media_role(org.id, owner, cover.id, "logo")
    assert orgs.get_by_id(org.id).logo_media_id == cover.id
    service.delete_media(org.id, owner, cover.id)
    assert orgs.get_by_id(org.id).logo_media_id is None


def test_upload_media_defaults_to_gallery() -> None:
    orgs_service, service, _, _, _ = make_media_services()
    owner = new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    snap = service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10)
    assert snap.kind == "image"
    assert snap.role == "gallery"


def test_upload_cover_demotes_previous_cover() -> None:
    orgs_service, service, _, media, _ = make_media_services()
    owner = new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    first = service.upload_media(
        org.id, owner, "a.png", "image/png", b"1" * 10, "cover"
    )
    second = service.upload_media(
        org.id, owner, "b.png", "image/png", b"1" * 10, "cover"
    )
    roles = {a.asset_id: a.role for a in media.list_by_org(org.id)}
    assert roles[first.id] == "gallery"
    assert roles[second.id] == "cover"


def test_brand_roles_are_image_only_and_owner_only() -> None:
    orgs_service, service, orgs, _, _ = make_media_services()
    owner, member = new_owner(), new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    orgs.members[org.id].add(member)
    with pytest.raises(InvalidMediaRoleError):
        service.upload_media(
            org.id, owner, "v.mp4", "video/mp4", b"1" * 10, "cover"
        )
    with pytest.raises(InvalidMediaRoleError):
        service.upload_media(
            org.id, owner, "a.png", "image/png", b"1" * 10, "weird"
        )
    with pytest.raises(ForbiddenError):
        service.upload_media(
            org.id, member, "a.png", "image/png", b"1" * 10, "logo"
        )
    member_gallery = service.upload_media(
        org.id, member, "a.png", "image/png", b"1" * 10
    )
    assert member_gallery.role == "gallery"


def test_set_media_role_owner_only_with_demotion() -> None:
    orgs_service, service, _, media, _ = make_media_services()
    owner, stranger = new_owner(), new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    one = service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10)
    two = service.upload_media(org.id, owner, "b.png", "image/png", b"1" * 10)

    with pytest.raises(ForbiddenError):
        service.set_media_role(org.id, stranger, one.id, "logo")
    with pytest.raises(NotFoundError):
        service.set_media_role(org.id, owner, new_owner(), "logo")

    assert service.set_media_role(org.id, owner, one.id, "logo").role == "logo"
    assert service.set_media_role(org.id, owner, two.id, "logo").role == "logo"
    assert media.get_asset(one.id).role == "gallery"
    assert media.get_asset(two.id).role == "logo"
    assert service.set_media_role(org.id, owner, two.id, "gallery").role == "gallery"


def test_set_media_role_on_video_rejected() -> None:
    orgs_service, service, _, _, _ = make_media_services()
    owner = new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    clip = service.upload_media(org.id, owner, "v.mp4", "video/mp4", b"1" * 10)
    with pytest.raises(InvalidMediaRoleError):
        service.set_media_role(org.id, owner, clip.id, "cover")


def test_list_media_surfaces_role() -> None:
    orgs_service, service, _, _, _ = make_media_services()
    owner = new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10, "cover")
    listed = service.list_media(org.id, owner)
    assert listed[0].role == "cover"


def test_delete_all_media_owner_only() -> None:
    orgs_service, service, _, media, _ = make_media_services()
    owner, stranger = new_owner(), new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10)
    service.upload_media(org.id, owner, "b.png", "image/png", b"1" * 10)

    with pytest.raises(ForbiddenError):
        service.delete_all_media(org.id, stranger)

    assert service.delete_all_media(org.id, owner) == 2
    assert media.list_by_org(org.id) == []
    assert service.delete_all_media(org.id, owner) == 0


def test_replace_media_rewrites_bytes_in_place() -> None:
    orgs_service, service, orgs, media, store = make_media_services()
    owner = new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    snap = service.upload_media(
        org.id, owner, "a.png", "image/png", b"1" * 10, "cover"
    )
    old_url = media.get_asset(snap.id).file_url

    edited = service.replace_media(
        org.id, owner, snap.id, "a-edit.png", "image/png", b"2" * 40
    )
    assert edited.id == snap.id
    assert edited.role == "cover"
    assert edited.size_bytes == 40
    assert edited.original_name == "a-edit.png"
    assert edited.updated_at is not None
    assert orgs.get_by_id(org.id).cover_media_id == snap.id
    assert store.files[media.get_asset(snap.id).file_url] == b"2" * 40
    assert old_url == media.get_asset(snap.id).file_url


def test_replace_media_sweeps_old_file_when_path_moves() -> None:
    orgs_service, service, _, media, store = make_media_services()
    owner = new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    snap = service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10)
    old_url = media.get_asset(snap.id).file_url

    # The FakeStore maps jpeg uploads to a .jpg path, so the file moves.
    edited = service.replace_media(
        org.id, owner, snap.id, "a.jpg", "image/jpeg", b"3" * 20
    )
    assert edited.mime == "image/jpeg"
    assert media.get_asset(snap.id).file_url != old_url
    assert old_url not in store.files


def test_replace_media_rules() -> None:
    orgs_service, service, _, media, _ = make_media_services()
    owner, stranger = new_owner(), new_owner()
    org = orgs_service.create_org(owner, "Club A", "club-a", "", "club")
    snap = service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10)
    clip = service.upload_media(org.id, owner, "v.mp4", "video/mp4", b"1" * 10)

    with pytest.raises(ForbiddenError):
        service.replace_media(
            org.id, stranger, snap.id, "b.png", "image/png", b"2" * 10
        )
    with pytest.raises(NotFoundError):
        service.replace_media(
            org.id, owner, new_owner(), "b.png", "image/png", b"2" * 10
        )
    with pytest.raises(UnsupportedMediaError):
        service.replace_media(
            org.id, owner, clip.id, "v.mp4", "video/mp4", b"2" * 10
        )
    with pytest.raises(UnsupportedMediaError):
        service.replace_media(
            org.id, owner, snap.id, "v.mp4", "video/mp4", b"2" * 10
        )
    with pytest.raises(MediaTooLargeError):
        service.replace_media(
            org.id,
            owner,
            snap.id,
            "big.png",
            "image/png",
            b"2" * (10 * 1024 * 1024 + 1),
        )
    # Failed attempts leave the stored bytes untouched.
    assert media.get_asset(snap.id).size_bytes == 10
