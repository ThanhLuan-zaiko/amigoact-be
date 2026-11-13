"""Joining, leaving, applications, member roles, and removing members."""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.models.auth import User
from src.models.organizations import (
    MembershipApplication,
    Organization,
    OrganizationMember,
    Role,
    UserRole,
)
from src.notifications.events import notify, organization_data
from src.organizations import signals
from src.organizations.access import (
    ACTIVE,
    ADMIN_ROLE_CODE,
    get_access,
    permissions_by_user,
    resolve_role,
)
from src.organizations.application_notices import tell_managers, withdraw_notices
from src.organizations.departure import member_gone
from src.organizations.roles import member_role_badges
from src.organizations.schemas import (
    ApplicationPage,
    ApplicationResponse,
    MemberPage,
    MemberResponse,
)
from src.organizations.service import APPLIED, reapply_time
from src.pagination import count_rows

JOIN_LIMIT = 30
JOIN_WINDOW = 60 * 60
LEFT = "left"
REVOKED = "revoked"
SUSPENDED = "suspended"


def _locked_member(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember | None:
    return db.get(OrganizationMember, (org_id, user_id), with_for_update=True)


def _clear_roles(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db.execute(
        delete(UserRole).where(UserRole.org_id == org_id, UserRole.user_id == user_id)
    )


def _save_member(
    db: Session,
    member: OrganizationMember | None,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    new_status: str,
    joined_at: datetime | None,
) -> None:
    if member is None:
        db.add(
            OrganizationMember(
                org_id=org_id, user_id=user_id, status=new_status, joined_at=joined_at
            )
        )
    else:
        member.status = new_status
        member.joined_at = joined_at


def _reject_blocked_status(member: OrganizationMember | None) -> None:
    if member is None:
        return
    if member.status == ACTIVE:
        raise api_error(status.HTTP_409_CONFLICT, "already_member")
    if member.status == APPLIED:
        raise api_error(status.HTTP_409_CONFLICT, "already_applied")
    if member.status == SUSPENDED:
        raise api_error(status.HTTP_403_FORBIDDEN, "membership_suspended")


def _submit_application(
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    message: str | None,
    now: datetime,
) -> None:
    application = db.get(MembershipApplication, (org_id, user_id))
    if application is None:
        application = MembershipApplication(org_id=org_id, user_id=user_id)
        db.add(application)
    elif reapply_time(application.rejected_at, now) is not None:
        raise api_error(status.HTTP_409_CONFLICT, "application_cooldown")
    application.answers = {"message": message} if message else None
    application.submitted_at = now
    application.rejected_at = None


def join_organization(
    db: Session, org: Organization, user_id: uuid.UUID, message: str | None
) -> None:
    """Join an open organization, or apply to one that approves its members.

    A removed member always goes through approval, so removal holds in open ones too.
    """
    enforce_rate_limit(db, f"org-join:{user_id}", JOIN_LIMIT, JOIN_WINDOW)
    org_id = org.id
    now = datetime.now(UTC)
    member = _locked_member(db, org_id, user_id)
    _reject_blocked_status(member)

    needs_approval = org.join_policy != "open" or (
        member is not None and member.status == REVOKED
    )
    if needs_approval:
        _submit_application(db, org_id, user_id, message, now)
        _save_member(db, member, org_id, user_id, new_status=APPLIED, joined_at=None)
        tell_managers(db, org, user_id, message)
        signals.applications_changed(db, org_id)
    else:
        _save_member(db, member, org_id, user_id, new_status=ACTIVE, joined_at=now)
        signals.members_changed(db, org_id)
    signals.membership_changed(db, org_id, user_id)
    try:
        db.commit()
    except IntegrityError as exc:
        # A second request for the same user inserted the row first.
        db.rollback()
        raise api_error(status.HTTP_409_CONFLICT, "already_member") from exc


def leave_organization(db: Session, org: Organization, user_id: uuid.UUID) -> None:
    """Leave, or withdraw a pending application."""
    if org.owner_id == user_id:
        raise api_error(status.HTTP_409_CONFLICT, "owner_cannot_leave")
    member = _locked_member(db, org.id, user_id)
    if member is None or member.status not in (ACTIVE, APPLIED):
        raise api_error(status.HTTP_404_NOT_FOUND, "not_a_member")
    if member.status == APPLIED:
        db.delete(member)
        db.execute(
            delete(MembershipApplication).where(
                MembershipApplication.org_id == org.id,
                MembershipApplication.user_id == user_id,
            )
        )
        withdraw_notices(db, org, user_id)
        signals.applications_changed(db, org.id)
        signals.membership_changed(db, org.id, user_id)
    else:
        member.status = LEFT
        _clear_roles(db, org.id, user_id)
        member_gone(db, org, user_id, removed=False)
    db.commit()


def list_members(db: Session, org: Organization, limit: int, offset: int) -> MemberPage:
    """Contact details stay out of this list, which every member can read."""
    staff = {
        user_id for user_id, held in permissions_by_user(db, org.id).items() if held
    }
    query = (
        select(OrganizationMember, User.full_name)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.org_id == org.id, OrganizationMember.status == ACTIVE)
    )
    rows = db.execute(
        query.order_by(OrganizationMember.joined_at, OrganizationMember.user_id)
        .limit(limit + 1)
        .offset(offset)
    ).all()
    page = rows[:limit]
    badges = member_role_badges(db, org.id, [member.user_id for member, _ in page])
    items = []
    for member, full_name in page:
        role = resolve_role(
            is_owner=org.owner_id == member.user_id,
            is_admin=member.user_id in staff,
            status=member.status,
        )
        items.append(
            MemberResponse(
                user_id=member.user_id,
                full_name=full_name,
                role=role or "member",
                roles=badges.get(member.user_id, []),
                joined_at=member.joined_at,
            )
        )
    return MemberPage(
        items=items,
        next_offset=offset + limit if len(rows) > limit else None,
        total=count_rows(db, query),
    )


def list_applications(
    db: Session, org: Organization, limit: int, offset: int
) -> ApplicationPage:
    """Return pending applications, oldest first."""
    query = (
        select(MembershipApplication, User.full_name)
        .join(User, User.id == MembershipApplication.user_id)
        .join(
            OrganizationMember,
            (OrganizationMember.org_id == MembershipApplication.org_id)
            & (OrganizationMember.user_id == MembershipApplication.user_id),
        )
        .where(
            MembershipApplication.org_id == org.id,
            OrganizationMember.status == APPLIED,
        )
    )
    rows = db.execute(
        query.order_by(
            MembershipApplication.submitted_at, MembershipApplication.user_id
        )
        .limit(limit + 1)
        .offset(offset)
    ).all()
    return ApplicationPage(
        items=[
            ApplicationResponse(
                user_id=application.user_id,
                full_name=full_name,
                message=(application.answers or {}).get("message"),
                submitted_at=application.submitted_at,
            )
            for application, full_name in rows[:limit]
        ],
        next_offset=offset + limit if len(rows) > limit else None,
        total=count_rows(db, query),
    )


def _pending_application(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[OrganizationMember, MembershipApplication]:
    member = _locked_member(db, org_id, user_id)
    application = db.get(MembershipApplication, (org_id, user_id))
    if member is None or member.status != APPLIED or application is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "application_not_found")
    return member, application


def approve_application(db: Session, org: Organization, user_id: uuid.UUID) -> None:
    member, application = _pending_application(db, org.id, user_id)
    member.status = ACTIVE
    member.joined_at = datetime.now(UTC)
    db.delete(application)
    notify(db, user_id, "membership_approved", organization_data(org))
    signals.applications_changed(db, org.id)
    signals.members_changed(db, org.id)
    signals.membership_changed(db, org.id, user_id)
    db.commit()


def reject_application(db: Session, org: Organization, user_id: uuid.UUID) -> None:
    """Keep the application row, because rejected_at controls the cooldown."""
    member, application = _pending_application(db, org.id, user_id)
    db.delete(member)
    application.answers = None
    application.rejected_at = datetime.now(UTC)
    notify(db, user_id, "membership_rejected", organization_data(org))
    signals.applications_changed(db, org.id)
    signals.membership_changed(db, org.id, user_id)
    db.commit()


def _active_member(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember:
    member = _locked_member(db, org_id, user_id)
    if member is None or member.status != ACTIVE:
        raise api_error(status.HTTP_404_NOT_FOUND, "member_not_found")
    return member


def set_member_role(
    db: Session, org: Organization, actor_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> None:
    if org.owner_id == user_id:
        raise api_error(status.HTTP_409_CONFLICT, "owner_role_locked")
    _active_member(db, org.id, user_id)
    if role == "member":
        _clear_roles(db, org.id, user_id)
        signals.lose_manager_role(db, org.id, user_id)
    else:
        admin_role_id = db.scalar(
            select(Role.id).where(Role.org_id == org.id, Role.code == ADMIN_ROLE_CODE)
        )
        if admin_role_id is None:
            # The owner deleted the Admin role, so there is nothing to hand out.
            raise api_error(status.HTTP_404_NOT_FOUND, "role_not_found")
        db.execute(
            insert(UserRole)
            .values(
                org_id=org.id,
                user_id=user_id,
                role_id=admin_role_id,
                granted_by=actor_id,
            )
            .on_conflict_do_nothing()
        )
    signals.members_changed(db, org.id)
    signals.membership_changed(db, org.id, user_id)
    db.commit()


def remove_member(
    db: Session, org: Organization, actor_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Nobody removes the owner, or a member whose top role is not below their own."""
    if org.owner_id == user_id:
        raise api_error(status.HTTP_409_CONFLICT, "owner_cannot_be_removed")
    if actor_id == user_id:
        raise api_error(status.HTTP_409_CONFLICT, "cannot_remove_self")
    outranked = (
        get_access(db, org, user_id).top_position
        >= get_access(db, org, actor_id).top_position
    )
    if org.owner_id != actor_id and outranked:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    member = _active_member(db, org.id, user_id)
    member.status = REVOKED
    _clear_roles(db, org.id, user_id)
    member_gone(db, org, user_id, removed=True)
    db.commit()
