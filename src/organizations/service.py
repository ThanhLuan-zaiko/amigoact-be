"""Creating, finding, and editing organizations."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.models.activities import Activity
from src.models.attendance import VolunteerHourLedger
from src.models.auth import User
from src.models.organizations import (
    MembershipApplication,
    Organization,
    OrganizationMember,
    Role,
    UserRole,
)
from src.organizations.access import ACTIVE, ADMIN_ROLE_CODE, get_access, resolve_role
from src.organizations.schemas import (
    MyOrganization,
    OrganizationCreateRequest,
    OrganizationDetail,
    OrganizationPage,
    OrganizationSummary,
    OrganizationUpdateRequest,
    ViewerMembership,
)
from src.organizations.slugs import candidate_slug, slugify

HOUR = 60 * 60
CREATE_LIMIT = 10
CREATE_WINDOW = HOUR
SLUG_ATTEMPTS = 5
ADMIN_ROLE_NAME = "Admin"
ADMIN_ROLE_POSITION = 100
REAPPLY_COOLDOWN = timedelta(days=7)
APPLIED = "applied"


def live_organization() -> tuple[Any, ...]:
    """Deleted and suspended organizations are hidden from every public read."""
    return (Organization.deleted_at.is_(None), Organization.status == ACTIVE)


def _member_count() -> Any:
    """Count per row of an outer query that selects from Organization."""
    members = aliased(OrganizationMember)
    return (
        select(func.count())
        .select_from(members)
        .where(members.org_id == Organization.id, members.status == ACTIVE)
        .correlate(Organization)
        .scalar_subquery()
    )


def load_organization(db: Session, slug: str) -> Organization:
    """Deleted and suspended organizations look like they do not exist."""
    org = db.scalar(
        select(Organization).where(Organization.slug == slug, *live_organization())
    )
    if org is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "organization_not_found")
    return org


def reapply_time(rejected_at: datetime | None, now: datetime) -> datetime | None:
    """Return when a rejected applicant may apply again, or None if they may now."""
    if rejected_at is None or rejected_at + REAPPLY_COOLDOWN <= now:
        return None
    return rejected_at + REAPPLY_COOLDOWN


def _summary_fields(org: Organization, member_count: int) -> dict[str, Any]:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "description": org.description,
        "org_type": org.org_type,
        "join_policy": org.join_policy,
        "member_count": member_count,
        "created_at": org.created_at,
    }


def viewer_membership(
    db: Session, org: Organization, user_id: uuid.UUID | None
) -> ViewerMembership:
    if user_id is None:
        return ViewerMembership()
    access = get_access(db, org, user_id)
    application = db.get(MembershipApplication, (org.id, user_id))
    rejected_at = application.rejected_at if application else None
    return ViewerMembership(
        status=access.status,
        role=access.role,
        can_manage=access.can_manage,
        reapply_after=reapply_time(rejected_at, datetime.now(UTC)),
    )


def _activity_count(db: Session, org_id: uuid.UUID) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(Activity)
        .where(
            Activity.org_id == org_id,
            Activity.deleted_at.is_(None),
            Activity.status != "draft",
        )
    )
    return count or 0


def _volunteer_hours(db: Session, org_id: uuid.UUID) -> float:
    total = db.scalar(
        select(func.sum(VolunteerHourLedger.hours)).where(
            VolunteerHourLedger.org_id == org_id,
            VolunteerHourLedger.status == "approved",
        )
    )
    return float(total or 0)


def organization_detail(
    db: Session, org: Organization, user_id: uuid.UUID | None
) -> OrganizationDetail:
    member_count = db.scalar(
        select(func.count())
        .select_from(OrganizationMember)
        .where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.status == ACTIVE,
        )
    )
    owner = db.get(User, org.owner_id)
    return OrganizationDetail(
        **_summary_fields(org, member_count or 0),
        email=org.email,
        phone=org.phone,
        website=org.website,
        address=org.address,
        city=org.city,
        owner_name=owner.full_name if owner else "",
        activity_count=_activity_count(db, org.id),
        volunteer_hours=_volunteer_hours(db, org.id),
        viewer=viewer_membership(db, org, user_id),
    )


def _insert_with_unique_slug(
    db: Session, payload: OrganizationCreateRequest, owner_id: uuid.UUID
) -> Organization:
    base = slugify(payload.name)
    for attempt in range(SLUG_ATTEMPTS):
        org = Organization(
            id=uuid.uuid7(),
            name=payload.name,
            slug=candidate_slug(base, attempt),
            description=payload.description,
            org_type=payload.org_type,
            join_policy=payload.join_policy,
            owner_id=owner_id,
        )
        db.add(org)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            if "organizations_slug_uq" not in str(exc.orig):
                raise api_error(status.HTTP_409_CONFLICT, "conflict") from exc
            continue
        return org
    raise api_error(status.HTTP_409_CONFLICT, "conflict")


def create_organization(
    db: Session, payload: OrganizationCreateRequest, owner_id: uuid.UUID
) -> Organization:
    """Create the organization with its owner as the first active member."""
    enforce_rate_limit(db, f"org-create:{owner_id}", CREATE_LIMIT, CREATE_WINDOW)
    org = _insert_with_unique_slug(db, payload, owner_id)
    db.add(
        OrganizationMember(
            org_id=org.id,
            user_id=owner_id,
            status=ACTIVE,
            joined_at=datetime.now(UTC),
        )
    )
    db.add(
        Role(
            id=uuid.uuid7(),
            org_id=org.id,
            code=ADMIN_ROLE_CODE,
            name=ADMIN_ROLE_NAME,
            is_system=True,
            position=ADMIN_ROLE_POSITION,
        )
    )
    db.commit()
    return org


def update_organization(
    db: Session, org: Organization, payload: OrganizationUpdateRequest
) -> Organization:
    for field in payload.model_fields_set:
        setattr(org, field, getattr(payload, field))
    db.commit()
    return org


def _page_of_summaries(
    db: Session, query: Select[Any], limit: int, offset: int
) -> OrganizationPage:
    rows = db.execute(query.limit(limit + 1).offset(offset)).all()
    return OrganizationPage(
        items=[
            OrganizationSummary(**_summary_fields(org, count))
            for org, count in rows[:limit]
        ],
        next_offset=offset + limit if len(rows) > limit else None,
    )


def list_organizations(
    db: Session, search: str | None, limit: int, offset: int
) -> OrganizationPage:
    query = select(Organization, _member_count()).where(*live_organization())
    if search:
        query = query.where(Organization.name.icontains(search, autoescape=True))
    query = query.order_by(Organization.created_at.desc(), Organization.id)
    return _page_of_summaries(db, query, limit, offset)


def _admin_org_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows: Sequence[uuid.UUID] = db.scalars(
        select(UserRole.org_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id, Role.code == ADMIN_ROLE_CODE)
    ).all()
    return set(rows)


def list_my_organizations(db: Session, user_id: uuid.UUID) -> list[MyOrganization]:
    """Return the organizations the user belongs to or has applied to."""
    admin_of = _admin_org_ids(db, user_id)
    rows = db.execute(
        select(Organization, _member_count(), OrganizationMember.status)
        .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.status.in_((ACTIVE, APPLIED)),
            *live_organization(),
        )
        .order_by(Organization.name)
    ).all()
    return [
        MyOrganization(
            **_summary_fields(org, count),
            status=member_status,
            role=resolve_role(
                is_owner=org.owner_id == user_id,
                is_admin=org.id in admin_of,
                status=member_status,
            ),
        )
        for org, count, member_status in rows
    ]
