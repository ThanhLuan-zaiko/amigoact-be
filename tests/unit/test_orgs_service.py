"""Unit tests for OrgService with a fake repository (no I/O, fast)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidBusinessProfileError,
    InvalidMediaRoleError,
    NotFoundError,
    SlugTakenError,
)
from core.media import MediaStore
from orgs.interfaces import MediaRepository, OrgRepository
from orgs.service import OrgService


class FakeOrgs(OrgRepository):
    def __init__(self) -> None:
        self.orgs: dict[UUID, Any] = {}
        self.slugs: dict[str, UUID] = {}
        self.members: dict[UUID, set[UUID]] = {}

    def create(self, org_id, owner_id, name, slug, description, kind, tax_code, legal_rep_name, legal_rep_id, legal_rep_position, legal_status, now):  # noqa: ANN001, ANN202
        if slug in self.slugs:
            raise SlugTakenError("Organization slug is already taken.")
        org = SimpleNamespace(
            id=org_id, owner_id=owner_id, name=name, slug=slug,
            description=description, org_type=kind, tax_code=tax_code,
            legal_rep_name=legal_rep_name, legal_rep_id=legal_rep_id,
            legal_rep_position=legal_rep_position, legal_status=legal_status,
            status="active", deleted_at=None,
            created_at=now, updated_at=now,
        )
        self.orgs[org_id] = org
        self.slugs[slug] = org_id
        self.members.setdefault(org_id, set()).add(owner_id)
        return org

    def get_by_id(self, org_id):  # noqa: ANN001, ANN202
        return self.orgs.get(org_id)

    def get_by_slug(self, slug):  # noqa: ANN001, ANN202
        org_id = self.slugs.get(slug)
        return self.orgs.get(org_id) if org_id else None

    def list_by_user(self, user_id):  # noqa: ANN001, ANN202
        return [o for oid, o in self.orgs.items() if user_id in self.members.get(oid, set())]

    def count_members(self, org_id):  # noqa: ANN001, ANN202
        return len(self.members.get(org_id, set()))

    def is_member(self, org_id, user_id):  # noqa: ANN001, ANN202
        return user_id in self.members.get(org_id, set())

    def update_details(self, org_id, name, description, now):  # noqa: ANN001, ANN202
        org = self.orgs.get(org_id)
        if org is None:
            return None
        org.name = name
        org.description = description
        org.updated_at = now
        return org

    def mark_deleted(self, org_id, now):  # noqa: ANN001, ANN202
        org = self.orgs.get(org_id)
        if org is None:
            return None
        org.deleted_at = now
        org.updated_at = now
        return org

    def mark_restored(self, org_id, now):  # noqa: ANN001, ANN202
        org = self.orgs.get(org_id)
        if org is None:
            return None
        org.deleted_at = None
        org.updated_at = now
        return org

    def delete_everything(self, org_id):  # noqa: ANN001, ANN202
        org = self.orgs.pop(org_id, None)
        if org is None:
            return False
        self.slugs.pop(org.slug, None)
        self.members.pop(org_id, None)
        return True


class FakeMedia(MediaRepository):
    def __init__(self) -> None:
        self.assets: dict[UUID, Any] = {}

    def create_asset(self, asset_id, org_id, file_url, mime, size_bytes, now, role="gallery"):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            asset_id=asset_id, owner_id=org_id, file_url=file_url,
            mime=mime, size_bytes=size_bytes, role=role, created_at=now,
        )
        self.assets[asset_id] = row
        return row

    def list_by_org(self, org_id):  # noqa: ANN001, ANN202
        return [a for a in self.assets.values() if a.owner_id == org_id]

    def get_asset(self, asset_id):  # noqa: ANN001, ANN202
        return self.assets.get(asset_id)

    def set_role(self, asset_id, role):  # noqa: ANN001, ANN202
        row = self.assets.get(asset_id)
        if row is None:
            return None
        row.role = role
        return row

    def delete_asset(self, asset_id):  # noqa: ANN001, ANN202
        return self.assets.pop(asset_id, None)

    def known_org_ids(self):  # noqa: ANN001, ANN202
        return {str(a.owner_id) for a in self.assets.values()}


class FakeStore(MediaStore):
    def save(self, org_id, media_id, filename, content):  # noqa: ANN001, ANN202
        return f"orgs/{org_id}/{media_id}"

    def save_typed(self, org_id, media_id, mime, filename, content):  # noqa: ANN001, ANN202
        return f"orgs/{org_id}/{media_id}"

    def resolve(self, relative_path):  # noqa: ANN001, ANN202
        raise ValueError("no disk")

    def delete_file(self, relative_path):  # noqa: ANN001, ANN202
        return False

    def delete_org_dir(self, org_id):  # noqa: ANN001, ANN202
        return False

    def sweep_orphans(self, known_org_ids):  # noqa: ANN001, ANN202
        return 0


def _media_service() -> tuple[OrgService, FakeOrgs, FakeMedia]:
    orgs, media = FakeOrgs(), FakeMedia()
    return OrgService(orgs, media, FakeStore()), orgs, media


def _owner() -> UUID:
    import uuid_utils

    return UUID(str(uuid_utils.uuid7()))


def test_create_club_without_legal_identity() -> None:
    service = OrgService(FakeOrgs())
    snapshot = service.create_org(_owner(), "Club A", "club-a", "", "club")
    assert snapshot.legal_status == "none"
    assert snapshot.member_count == 1


def test_create_business_requires_legal_head() -> None:
    service = OrgService(FakeOrgs())
    with pytest.raises(InvalidBusinessProfileError):
        service.create_org(_owner(), "Biz", "biz-1", "", "business")
    snapshot = service.create_org(
        _owner(), "Biz", "biz-1", "", "business",
        "0312345678", "Nguyen Van A", "012345678901", "Giam doc",
    )
    assert snapshot.legal_status == "pending"
    assert snapshot.tax_code == "0312345678"


def test_duplicate_slug_rejected() -> None:
    service = OrgService(FakeOrgs())
    owner = _owner()
    service.create_org(owner, "Club A", "club-a", "", "club")
    with pytest.raises(SlugTakenError):
        service.create_org(owner, "Club B", "club-a", "", "group")


def test_list_mine_returns_only_owner_orgs() -> None:
    repo = FakeOrgs()
    service = OrgService(repo)
    mine, other = _owner(), _owner()
    service.create_org(mine, "Mine", "mine-1", "", "group")
    service.create_org(other, "Other", "other-1", "", "group")
    assert [o.slug for o in service.list_my_orgs(mine)] == ["mine-1"]
    assert isinstance(datetime.now(timezone.utc), datetime)


def test_update_soft_restore_hard_cycle() -> None:
    from core.exceptions import ForbiddenError, NotFoundError, OrgDeletedError

    service = OrgService(FakeOrgs())
    owner, stranger = _owner(), _owner()
    created = service.create_org(owner, "Club A", "club-a", "Old", "club")

    renamed = service.update_org(created.id, owner, "Club B", "New")
    assert renamed.name == "Club B"
    with pytest.raises(ForbiddenError):
        service.update_org(created.id, stranger, "Hijack", "")

    trashed = service.soft_delete_org(created.id, owner)
    assert trashed.deleted_at is not None
    assert service.list_my_orgs(owner) == []
    assert [o.slug for o in service.list_my_orgs(owner, include_deleted=True)] == ["club-a"]
    with pytest.raises(OrgDeletedError):
        service.update_org(created.id, owner, "Again", "")

    restored = service.restore_org(created.id, owner)
    assert restored.deleted_at is None
    assert [o.slug for o in service.list_my_orgs(owner)] == ["club-a"]

    with pytest.raises(ForbiddenError):
        service.hard_delete_org(created.id, stranger)
    assert service.hard_delete_org(created.id, owner) == 0
    with pytest.raises(NotFoundError):
        service.update_org(created.id, owner, "Ghost", "")


def test_restore_live_org_rejected() -> None:
    service = OrgService(FakeOrgs())
    owner = _owner()
    created = service.create_org(owner, "Club A", "club-a", "", "club")
    with pytest.raises(InvalidBusinessProfileError):
        service.restore_org(created.id, owner)


def test_upload_media_defaults_to_gallery() -> None:
    service, _, _ = _media_service()
    owner = _owner()
    org = service.create_org(owner, "Club A", "club-a", "", "club")
    snap = service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10)
    assert snap.kind == "image"
    assert snap.role == "gallery"


def test_upload_cover_demotes_previous_cover() -> None:
    service, _, media = _media_service()
    owner = _owner()
    org = service.create_org(owner, "Club A", "club-a", "", "club")
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
    service, orgs, _ = _media_service()
    owner, member = _owner(), _owner()
    org = service.create_org(owner, "Club A", "club-a", "", "club")
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
    service, _, media = _media_service()
    owner, stranger = _owner(), _owner()
    org = service.create_org(owner, "Club A", "club-a", "", "club")
    one = service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10)
    two = service.upload_media(org.id, owner, "b.png", "image/png", b"1" * 10)

    with pytest.raises(ForbiddenError):
        service.set_media_role(org.id, stranger, one.id, "logo")
    with pytest.raises(NotFoundError):
        service.set_media_role(org.id, owner, _owner(), "logo")

    assert service.set_media_role(org.id, owner, one.id, "logo").role == "logo"
    assert service.set_media_role(org.id, owner, two.id, "logo").role == "logo"
    assert media.get_asset(one.id).role == "gallery"
    assert media.get_asset(two.id).role == "logo"
    assert service.set_media_role(org.id, owner, two.id, "gallery").role == "gallery"


def test_set_media_role_on_video_rejected() -> None:
    service, _, _ = _media_service()
    owner = _owner()
    org = service.create_org(owner, "Club A", "club-a", "", "club")
    clip = service.upload_media(org.id, owner, "v.mp4", "video/mp4", b"1" * 10)
    with pytest.raises(InvalidMediaRoleError):
        service.set_media_role(org.id, owner, clip.id, "cover")


def test_list_media_surfaces_role() -> None:
    service, _, _ = _media_service()
    owner = _owner()
    org = service.create_org(owner, "Club A", "club-a", "", "club")
    service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10, "cover")
    listed = service.list_media(org.id, owner)
    assert listed[0].role == "cover"


def test_delete_all_media_owner_only() -> None:
    service, _, media = _media_service()
    owner, stranger = _owner(), _owner()
    org = service.create_org(owner, "Club A", "club-a", "", "club")
    service.upload_media(org.id, owner, "a.png", "image/png", b"1" * 10)
    service.upload_media(org.id, owner, "b.png", "image/png", b"1" * 10)

    with pytest.raises(ForbiddenError):
        service.delete_all_media(org.id, stranger)

    assert service.delete_all_media(org.id, owner) == 2
    assert media.list_by_org(org.id) == []
    assert service.delete_all_media(org.id, owner) == 0
