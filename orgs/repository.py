"""cqlengine persistence for orgs. Slug claims use LWT raw CQL."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from core.exceptions import SlugTakenError
from core.ids import uuid7
from orgs.interfaces import MediaRepository, OrgRepository
from orgs.model import (
    MediaAsset,
    MediaByOwner,
    MemberByUser,
    Organization,
    OrganizationMember,
    OrganizationsBySlug,
)


class CqlOrgRepository(OrgRepository):
    """Orgs plus slug index and dual membership query tables."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def create(
        self,
        org_id: UUID,
        owner_id: UUID,
        name: str,
        slug: str,
        description: str,
        kind: str,
        tax_code: str | None,
        legal_rep_name: str | None,
        legal_rep_id: str | None,
        legal_rep_position: str | None,
        legal_status: str,
        now: datetime,
    ) -> Organization:
        session = get_session()
        claim = session.execute(
            f"INSERT INTO {self._keyspace}.organizations_by_slug (slug, org_id)"
            " VALUES (%s, %s) IF NOT EXISTS",
            [slug, org_id],
        )
        if not claim.was_applied:
            raise SlugTakenError("Organization slug is already taken.")
        org = Organization.create(
            id=org_id,
            name=name,
            slug=slug,
            description=description,
            org_type=kind,
            status="active",
            owner_id=owner_id,
            tax_code=tax_code,
            legal_rep_name=legal_rep_name,
            legal_rep_id=legal_rep_id,
            legal_rep_position=legal_rep_position,
            legal_status=legal_status,
            created_at=now,
            updated_at=now,
        )
        OrganizationMember.create(
            org_id=org_id, user_id=owner_id, status="active", joined_at=now
        )
        MemberByUser.create(
            user_id=owner_id, org_id=org_id, status="active", joined_at=now
        )
        return org

    def get_by_id(self, org_id: UUID) -> Organization | None:
        return Organization.objects(id=org_id).first()

    def get_by_slug(self, slug: str) -> Organization | None:
        index = OrganizationsBySlug.objects(slug=slug).first()
        return self.get_by_id(index.org_id) if index else None

    def list_by_user(self, user_id: UUID) -> list[Organization]:
        orgs: list[Organization] = []
        for link in MemberByUser.objects(user_id=user_id).all():
            org = self.get_by_id(link.org_id)
            if org is not None:
                orgs.append(org)
        return orgs

    def count_members(self, org_id: UUID) -> int:
        return sum(1 for _ in OrganizationMember.objects(org_id=org_id).all())

    def is_member(self, org_id: UUID, user_id: UUID) -> bool:
        return (
            MemberByUser.objects(user_id=user_id, org_id=org_id).first() is not None
        )

    def update_details(
        self, org_id: UUID, name: str, description: str, now: datetime
    ) -> Organization | None:
        if self.get_by_id(org_id) is None:
            return None
        Organization.objects(id=org_id).update(
            name=name, description=description, updated_at=now
        )
        return self.get_by_id(org_id)

    def mark_deleted(self, org_id: UUID, now: datetime) -> Organization | None:
        if self.get_by_id(org_id) is None:
            return None
        Organization.objects(id=org_id).update(deleted_at=now, updated_at=now)
        return self.get_by_id(org_id)

    def mark_restored(self, org_id: UUID, now: datetime) -> Organization | None:
        if self.get_by_id(org_id) is None:
            return None
        Organization.objects(id=org_id).update(deleted_at=None, updated_at=now)
        return self.get_by_id(org_id)

    def delete_everything(self, org_id: UUID) -> bool:
        org = self.get_by_id(org_id)
        if org is None:
            return False
        for member in OrganizationMember.objects(org_id=org_id).all():
            MemberByUser.objects(user_id=member.user_id, org_id=org_id).delete()
            member.delete()
        for asset in MediaByOwner.objects(owner_id=org_id).all():
            MediaAsset.objects(asset_id=asset.asset_id).delete()
            asset.delete()
        OrganizationsBySlug.objects(slug=org.slug).delete()
        org.delete()
        return True


class CqlMediaRepository(MediaRepository):
    """Gallery metadata mirrored into the per-owner feed table."""

    def create_asset(
        self,
        asset_id: UUID,
        org_id: UUID,
        file_url: str,
        mime: str,
        size_bytes: int,
        now: datetime,
    ) -> MediaAsset:
        row = MediaAsset.create(
            asset_id=asset_id,
            owner_id=org_id,
            owner_type="organization",
            file_url=file_url,
            mime=mime,
            size_bytes=size_bytes,
            created_at=now,
        )
        MediaByOwner.create(
            owner_id=org_id,
            created_at=now,
            asset_id=asset_id,
            file_url=file_url,
            mime=mime,
            owner_type="organization",
        )
        return row

    def list_by_org(self, org_id: UUID) -> list[MediaAsset]:
        rows: list[MediaAsset] = []
        for link in MediaByOwner.objects(owner_id=org_id).all():
            asset = self.get_asset(link.asset_id)
            if asset is not None:
                rows.append(asset)
        return rows

    def get_asset(self, asset_id: UUID) -> MediaAsset | None:
        return MediaAsset.objects(asset_id=asset_id).first()

    def delete_asset(self, asset_id: UUID) -> MediaAsset | None:
        row = self.get_asset(asset_id)
        if row is None:
            return None
        for link in MediaByOwner.objects(owner_id=row.owner_id).all():
            if link.asset_id == asset_id:
                link.delete()
        row.delete()
        return row

    def known_org_ids(self) -> set[str]:
        return {str(org.id) for org in Organization.objects.all()}


def generate_org_id() -> UUID:
    """Application-side UUIDv7 primary key for new orgs."""
    return uuid7()
