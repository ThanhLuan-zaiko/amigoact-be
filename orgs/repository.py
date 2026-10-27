"""cqlengine persistence for orgs. Slug claims use LWT raw CQL."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID


from core.exceptions import SlugTakenError, TaxCodeTakenError
from orgs.directory_feed import delete_public_feed, write_public_feed
from orgs.interfaces import ORG_KINDS, OrgContactDetails, OrgRepository
from orgs.media_repository import media_feeds_delete
from orgs.model import (
    MediaAsset,
    MediaByOwner,
    MemberByUser,
    Organization,
    OrganizationMember,
    OrganizationsByLegalStatus,
    OrganizationsBySlug,
    OrganizationsByTaxCode,
    OrganizationsPublic,
)
from orgs.repo_helpers import contact_fields, queue_delete, queue_write
from core.cql import claim, run as cql_run
from orgs.public_cache import PUBLIC_ORGS_CACHE, invalidates_public, owns

class CqlOrgRepository(OrgRepository):
    """Orgs plus slug index and dual membership query tables."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    @invalidates_public
    def create(
        self,
        org_id: UUID,
        owner_id: UUID,
        name: str,
        slug: str,
        description: str,
        kind: str,
        join_policy: str,
        tax_code: str | None,
        legal_rep_name: str | None,
        legal_rep_id: str | None,
        legal_rep_position: str | None,
        legal_status: str,
        now: datetime,
        contact: OrgContactDetails | None = None,
    ) -> Organization:
        slug_applied = claim(
            f"INSERT INTO {self._keyspace}.organizations_by_slug (slug, org_id)"
            " VALUES (%s, %s) IF NOT EXISTS",
            [slug, org_id],
            lambda: owns(OrganizationsBySlug.objects(slug=slug).first(), org_id),
        )
        if not slug_applied:
            raise SlugTakenError("Organization slug is already taken.")
        if tax_code is not None:
            # One org per tax code; second claim fails and frees the slug.
            tax_applied = claim(
                f"INSERT INTO {self._keyspace}.organizations_by_tax_code"
                " (tax_code, org_id) VALUES (%s, %s) IF NOT EXISTS",
                [tax_code, org_id],
                lambda: owns(
                    OrganizationsByTaxCode.objects(tax_code=tax_code).first(),
                    org_id,
                ),
            )
            if not tax_applied:
                OrganizationsBySlug.objects(slug=slug).delete()
                raise TaxCodeTakenError("Tax code is already registered.")
        org = Organization.create(
            id=org_id,
            name=name,
            slug=slug,
            description=description,
            org_type=kind,
            status="active",
            join_policy=join_policy,
            owner_id=owner_id,
            tax_code=tax_code,
            legal_rep_name=legal_rep_name,
            legal_rep_id=legal_rep_id,
            legal_rep_position=legal_rep_position,
            legal_status=legal_status,
            created_at=now,
            updated_at=now,
            **contact_fields(contact),
        )
        queue_write(org)
        write_public_feed(org)
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
            # Invited/left rows stay out of the "my orgs" listing.
            if (getattr(link, "status", "active") or "active") != "active":
                continue
            org = self.get_by_id(link.org_id)
            if org is not None:
                orgs.append(org)
        return orgs

    def count_members(self, org_id: UUID) -> int:
        return sum(
            1
            for row in OrganizationMember.objects(org_id=org_id).all()
            if (getattr(row, "status", "active") or "active") == "active"
        )

    def is_member(self, org_id: UUID, user_id: UUID) -> bool:
        row = MemberByUser.objects(user_id=user_id, org_id=org_id).first()
        if row is None:
            return False
        return (getattr(row, "status", "active") or "active") == "active"

    def _claim_tax_change(
        self, org: Organization, legal: dict[str, object] | None
    ) -> str | None:
        """Claim a new tax code before the row moves; None when unchanged."""
        new_tax = legal.get("tax_code") if legal else None
        if not isinstance(new_tax, str) or not new_tax or new_tax == org.tax_code:
            return None
        claim = cql_run(
            f"INSERT INTO {self._keyspace}.organizations_by_tax_code"
            " (tax_code, org_id) VALUES (%s, %s) IF NOT EXISTS",
            [new_tax, org.id],
        )
        if not claim.was_applied:
            raise TaxCodeTakenError("Tax code is already registered.")
        return new_tax

    @invalidates_public
    def update_details(
        self,
        org_id: UUID,
        name: str,
        description: str,
        now: datetime,
        join_policy: str | None = None,
        contact: OrgContactDetails | None = None,
        legal: dict[str, object] | None = None,
    ) -> Organization | None:
        org = self.get_by_id(org_id)
        if org is None:
            return None
        fields: dict[str, object] = {
            "name": name,
            "description": description,
            "updated_at": now,
        }
        if join_policy is not None:
            fields["join_policy"] = join_policy
        fields.update(contact_fields(contact))
        claimed_tax = self._claim_tax_change(org, legal)
        if legal:
            fields.update(legal)
        try:
            Organization.objects(id=org_id).update(**fields)
        except Exception:
            if claimed_tax is not None:
                # Row update failed after claiming; free the new tax code.
                OrganizationsByTaxCode.objects(
                    tax_code=claimed_tax
                ).delete()
            raise
        if claimed_tax is not None and org.tax_code:
            # Row now points at the new code; release the previous claim.
            OrganizationsByTaxCode.objects(tax_code=org.tax_code).delete()
        # Keep the verification queue's denormalized copy fresh; the
        # upsert also self-heals rows created before the queue existed.
        OrganizationsByLegalStatus.objects(
            legal_status=org.legal_status or "none",
            created_at=org.created_at,
            org_id=org.id,
        ).update(name=name, slug=org.slug)
        # Same self-healing upsert for the public directory feed.
        OrganizationsPublic.objects(
            kind=org.org_type or "organization",
            created_at=org.created_at,
            org_id=org.id,
        ).update(name=name, slug=org.slug)
        return self.get_by_id(org_id)

    @invalidates_public
    def mark_deleted(self, org_id: UUID, now: datetime) -> Organization | None:
        org = self.get_by_id(org_id)
        if org is None:
            return None
        # Free the slug so a replacement org can take it while this one
        # sits in trash; restore reclaims it (suffix fallback on clashes).
        OrganizationsBySlug.objects(slug=org.slug).delete()
        queue_delete(org)
        delete_public_feed(org)
        Organization.objects(id=org_id).update(deleted_at=now, updated_at=now)
        return self.get_by_id(org_id)

    @invalidates_public
    def mark_restored(self, org_id: UUID, now: datetime) -> Organization | None:
        org = self.get_by_id(org_id)
        if org is None:
            return None
        original = org.slug
        chosen: str | None = None
        for candidate in (original, *(f"{original}-r{n}" for n in range(2, 6))):
            claim = cql_run(
                f"INSERT INTO {self._keyspace}.organizations_by_slug"
                " (slug, org_id) VALUES (%s, %s) IF NOT EXISTS",
                [candidate[:60], org_id],
            )
            if claim.was_applied:
                chosen = candidate[:60]
                break
        if chosen is None:
            raise SlugTakenError("Organization slug is already taken.")
        fields: dict[str, object] = {"deleted_at": None, "updated_at": now}
        if chosen != original:
            # Another org claimed the slug while this one was in trash.
            fields["slug"] = chosen
            fields["previous_slug"] = original
        Organization.objects(id=org_id).update(**fields)
        fresh = self.get_by_id(org_id)
        assert fresh is not None
        queue_write(fresh)
        write_public_feed(fresh)
        return fresh

    @invalidates_public
    def set_brand_media(
        self, org_id: UUID, role: str, asset_id: UUID | None, now: datetime
    ) -> None:
        column = {"cover": "cover_media_id", "logo": "logo_media_id"}.get(role)
        if column is None:
            return
        Organization.objects(id=org_id).update(
            **{column: asset_id, "updated_at": now}
        )

    def list_by_legal_status(
        self, legal_status: str, limit: int = 100
    ) -> list[Organization]:
        rows = OrganizationsByLegalStatus.objects(
            legal_status=legal_status
        ).limit(limit)
        orgs: list[Organization] = []
        for row in rows:
            org = self.get_by_id(row.org_id)
            if org is not None and org.deleted_at is None:
                orgs.append(org)
        return orgs

    def list_public(self) -> list[Organization]:
        """Cached merge of every public kind partition."""
        return list(PUBLIC_ORGS_CACHE.get_or_load(self._keyspace, self._load_public))

    def _load_public(self) -> list[Organization]:
        """Merge every kind partition; re-reads skip dead or hidden rows."""
        orgs: list[Organization] = []
        for kind in ORG_KINDS:
            for link in OrganizationsPublic.objects(kind=kind).all():
                org = self.get_by_id(link.org_id)
                if org is None or org.deleted_at is not None:
                    continue
                if (getattr(org, "status", "active") or "active") != "active":
                    continue
                orgs.append(org)
        return orgs

    @invalidates_public
    def set_legal_status(
        self,
        org_id: UUID,
        legal_status: str,
        verified_at: datetime | None,
        verified_by: UUID | None,
        now: datetime,
    ) -> Organization | None:
        org = self.get_by_id(org_id)
        if org is None:
            return None
        previous = org.legal_status or "none"
        # The queue is partitioned by status: drop the old bucket row and
        # write a fresh one so each status partition stays a clean feed.
        OrganizationsByLegalStatus.objects(
            legal_status=previous,
            created_at=org.created_at,
            org_id=org.id,
        ).delete()
        Organization.objects(id=org_id).update(
            legal_status=legal_status,
            verified_at=verified_at,
            verified_by=verified_by,
            updated_at=now,
        )
        fresh = self.get_by_id(org_id)
        assert fresh is not None
        queue_write(fresh)
        return fresh

    @invalidates_public
    def delete_everything(self, org_id: UUID) -> bool:
        org = self.get_by_id(org_id)
        if org is None:
            return False
        for member in OrganizationMember.objects(org_id=org_id).all():
            MemberByUser.objects(user_id=member.user_id, org_id=org_id).delete()
            member.delete()
        for asset in MediaByOwner.objects(owner_id=org_id).all():
            row = MediaAsset.objects(asset_id=asset.asset_id).first()
            if row is not None:
                media_feeds_delete(row)
                row.delete()
            asset.delete()
        OrganizationsBySlug.objects(slug=org.slug).delete()
        if org.tax_code:
            OrganizationsByTaxCode.objects(tax_code=org.tax_code).delete()
        queue_delete(org)
        delete_public_feed(org)
        org.delete()
        return True
