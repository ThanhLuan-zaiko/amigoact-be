"""Shared in-memory ports for OrgService/MediaService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from core.exceptions import SlugTakenError
from core.media import MediaStore
from orgs.interfaces import MediaRepository, OrgRepository
from orgs.media_service import MediaService
from orgs.service import OrgService


class FakeOrgs(OrgRepository):
    def __init__(self) -> None:
        self.orgs: dict[UUID, Any] = {}
        self.slugs: dict[str, UUID] = {}
        self.members: dict[UUID, set[UUID]] = {}

    def create(self, org_id, owner_id, name, slug, description, kind, join_policy, tax_code, legal_rep_name, legal_rep_id, legal_rep_position, legal_status, now, contact=None):  # noqa: ANN001, ANN202
        if slug in self.slugs:
            raise SlugTakenError("Organization slug is already taken.")
        extra = vars(contact) if contact is not None else {}
        org = SimpleNamespace(
            id=org_id, owner_id=owner_id, name=name, slug=slug,
            description=description, org_type=kind, join_policy=join_policy,
            tax_code=tax_code,
            legal_rep_name=legal_rep_name, legal_rep_id=legal_rep_id,
            legal_rep_position=legal_rep_position, legal_status=legal_status,
            status="active", deleted_at=None,
            verified_at=None, verified_by=None,
            cover_media_id=None, logo_media_id=None,
            created_at=now, updated_at=now, **extra,
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

    def update_details(self, org_id, name, description, now, join_policy=None, contact=None):  # noqa: ANN001, ANN202
        org = self.orgs.get(org_id)
        if org is None:
            return None
        org.name = name
        org.description = description
        if join_policy is not None:
            org.join_policy = join_policy
        if contact is not None:
            for key, value in vars(contact).items():
                setattr(org, key, value)
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

    def set_brand_media(self, org_id, role, asset_id, now):  # noqa: ANN001, ANN202
        org = self.orgs.get(org_id)
        if org is not None:
            setattr(org, f"{role}_media_id", asset_id)

    def list_by_legal_status(self, legal_status, limit=100):  # noqa: ANN001, ANN202
        return [
            o for o in self.orgs.values()
            if (o.legal_status or "none") == legal_status
            and o.deleted_at is None
        ][:limit]

    def set_legal_status(self, org_id, legal_status, verified_at, verified_by, now):  # noqa: ANN001, ANN202
        org = self.orgs.get(org_id)
        if org is None:
            return None
        org.legal_status = legal_status
        org.verified_at = verified_at
        org.verified_by = verified_by
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

    def create_asset(self, asset_id, org_id, file_url, mime, size_bytes, now, role="gallery", file_hash=None, uploader_id=None, original_name=None):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            asset_id=asset_id, owner_id=org_id, file_url=file_url,
            mime=mime, size_bytes=size_bytes, role=role, created_at=now,
            file_hash=file_hash, uploader_id=uploader_id,
            original_name=original_name, upload_status="active",
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

    def replace_content(self, asset_id, file_url, mime, size_bytes, file_hash, original_name, now):  # noqa: ANN001, ANN202
        row = self.assets.get(asset_id)
        if row is None:
            return None
        row.file_url = file_url
        row.mime = mime
        row.size_bytes = size_bytes
        row.file_hash = file_hash
        row.original_name = original_name
        row.updated_at = now
        return row

    def delete_asset(self, asset_id):  # noqa: ANN001, ANN202
        return self.assets.pop(asset_id, None)

    def known_org_ids(self):  # noqa: ANN001, ANN202
        return {str(a.owner_id) for a in self.assets.values()}


class FakeStore(MediaStore):
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def save(self, org_id, media_id, filename, content):  # noqa: ANN001, ANN202
        path = f"orgs/{org_id}/{media_id}"
        self.files[path] = content
        return path

    def save_typed(self, org_id, media_id, mime, filename, content):  # noqa: ANN001, ANN202
        ext = {"image/png": ".png", "image/jpeg": ".jpg"}.get(mime.split(";")[0], "")
        path = f"orgs/{org_id}/{media_id}{ext}"
        self.files[path] = content
        return path

    def resolve(self, relative_path):  # noqa: ANN001, ANN202
        raise ValueError("no disk")

    def delete_file(self, relative_path):  # noqa: ANN001, ANN202
        return self.files.pop(relative_path, None) is not None

    def delete_org_dir(self, org_id):  # noqa: ANN001, ANN202
        return False

    def sweep_orphans(self, known_org_ids):  # noqa: ANN001, ANN202
        return 0

    def save_user_media(self, user_id, media_id, mime, filename, content):  # noqa: ANN001, ANN202
        return f"users/{user_id}/{media_id}"

    def delete_user_dir(self, user_id):  # noqa: ANN001, ANN202
        return False


def make_media_services() -> (
    tuple[OrgService, MediaService, FakeOrgs, FakeMedia, FakeStore]
):
    orgs, media, store = FakeOrgs(), FakeMedia(), FakeStore()
    return (
        OrgService(orgs, media, store),
        MediaService(orgs, media, store),
        orgs,
        media,
        store,
    )


def new_owner() -> UUID:
    return UUID(str(uuid_utils.uuid7()))
