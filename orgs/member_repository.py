"""cqlengine persistence for memberships: dual query tables, no orgs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from orgs.interfaces import MemberRepository
from orgs.model import MemberByUser, OrganizationMember

try:
    from cassandra.cqlengine.query import BatchQuery
except ImportError:  # pragma: no cover - driver without batch support
    BatchQuery = None  # type: ignore[assignment]


class CqlMemberRepository(MemberRepository):
    """Membership rows written into both query directions."""

    def get(self, org_id: UUID, user_id: UUID) -> OrganizationMember | None:
        return OrganizationMember.objects(
            org_id=org_id, user_id=user_id
        ).first()

    def list_by_org(self, org_id: UUID) -> list[OrganizationMember]:
        return list(OrganizationMember.objects(org_id=org_id).all())

    def list_links_by_user(self, user_id: UUID) -> list[MemberByUser]:
        return list(MemberByUser.objects(user_id=user_id).all())

    def put(
        self,
        org_id: UUID,
        user_id: UUID,
        status: str,
        now: datetime,
        invited_by: UUID | None = None,
    ) -> OrganizationMember:
        if BatchQuery is not None:
            # Logged batch keeps both query tables in sync atomically.
            with BatchQuery() as batch:
                row = OrganizationMember.batch(batch).create(
                    org_id=org_id,
                    user_id=user_id,
                    status=status,
                    invited_by=invited_by,
                    joined_at=now,
                )
                MemberByUser.batch(batch).create(
                    user_id=user_id,
                    org_id=org_id,
                    status=status,
                    invited_by=invited_by,
                    joined_at=now,
                )
            return row
        # Fallback without batch support: best-effort with compensation.
        # If the second write fails, remove the first to avoid orphan rows.
        row = OrganizationMember.create(
            org_id=org_id,
            user_id=user_id,
            status=status,
            invited_by=invited_by,
            joined_at=now,
        )
        try:
            MemberByUser.create(
                user_id=user_id,
                org_id=org_id,
                status=status,
                invited_by=invited_by,
                joined_at=now,
            )
        except Exception:
            try:
                OrganizationMember.objects(
                    org_id=org_id, user_id=user_id
                ).delete()
            except Exception:
                pass
            raise
        return row

    def set_status(
        self,
        org_id: UUID,
        user_id: UUID,
        status: str,
        now: datetime,
        invited_by: UUID | None = None,
    ) -> OrganizationMember | None:
        existing = self.get(org_id, user_id)
        if existing is None:
            return None
        # A re-invite passes the new inviter; other transitions keep it.
        fields: dict[str, object] = {"status": status, "joined_at": now}
        if invited_by is not None:
            fields["invited_by"] = invited_by
        if BatchQuery is not None:
            # Logged batch applies the status change to both tables at once.
            with BatchQuery() as batch:
                OrganizationMember.objects(
                    org_id=org_id, user_id=user_id
                ).batch(batch).update(**fields)
                MemberByUser.objects(
                    user_id=user_id, org_id=org_id
                ).batch(batch).update(**fields)
            return self.get(org_id, user_id)
        # Fallback without batch: best-effort with revert on partial failure.
        # Updates are idempotent so a retry converges; revert keeps tables aligned.
        previous_status = getattr(existing, "status", "active") or "active"
        previous_joined = getattr(existing, "joined_at", now)
        OrganizationMember.objects(org_id=org_id, user_id=user_id).update(
            **fields
        )
        try:
            MemberByUser.objects(user_id=user_id, org_id=org_id).update(
                **fields
            )
        except Exception:
            try:
                OrganizationMember.objects(
                    org_id=org_id, user_id=user_id
                ).update(status=previous_status, joined_at=previous_joined)
            except Exception:
                pass
            raise
        return self.get(org_id, user_id)
