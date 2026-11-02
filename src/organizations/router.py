"""Routes for organizations and their members."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from src.auth.deps import CurrentPrincipal, Db, OptionalPrincipal
from src.organizations import membership, service
from src.organizations.access import require_manager, require_member, require_owner
from src.organizations.schemas import (
    ApplicationPage,
    JoinRequest,
    MemberPage,
    MemberRoleRequest,
    MyOrganization,
    OrganizationCreateRequest,
    OrganizationDetail,
    OrganizationPage,
    OrganizationUpdateRequest,
    ViewerMembership,
)
from src.validation import Uuid7

router = APIRouter(prefix="/organizations", tags=["organizations"])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
# The pattern rejects control characters. PostgreSQL does not accept NUL in text.
Search = Annotated[str | None, Query(max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreateRequest, principal: CurrentPrincipal, db: Db
) -> OrganizationDetail:
    user_id = principal.user.id
    org = service.create_organization(db, payload, user_id)
    return service.organization_detail(db, org, user_id)


@router.get("")
def list_organizations(
    db: Db, q: Search = None, limit: Limit = 20, offset: Offset = 0
) -> OrganizationPage:
    return service.list_organizations(db, q, limit, offset)


@router.get("/mine")
def list_my_organizations(principal: CurrentPrincipal, db: Db) -> list[MyOrganization]:
    return service.list_my_organizations(db, principal.user.id)


@router.get("/{slug}")
def get_organization(
    slug: Slug, db: Db, principal: OptionalPrincipal
) -> OrganizationDetail:
    org = service.load_organization(db, slug)
    return service.organization_detail(
        db, org, principal.user.id if principal else None
    )


@router.patch("/{slug}")
def update_organization(
    slug: Slug,
    payload: OrganizationUpdateRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> OrganizationDetail:
    user_id = principal.user.id
    org = service.load_organization(db, slug)
    require_manager(db, org, user_id)
    service.update_organization(db, org, payload)
    return service.organization_detail(db, org, user_id)


@router.post("/{slug}/join")
def join_organization(
    slug: Slug, payload: JoinRequest, principal: CurrentPrincipal, db: Db
) -> ViewerMembership:
    user_id = principal.user.id
    org = service.load_organization(db, slug)
    membership.join_organization(db, org, user_id, payload.message)
    return service.viewer_membership(db, org, user_id)


@router.delete("/{slug}/membership", status_code=status.HTTP_204_NO_CONTENT)
def leave_organization(slug: Slug, principal: CurrentPrincipal, db: Db) -> None:
    org = service.load_organization(db, slug)
    membership.leave_organization(db, org, principal.user.id)


@router.get("/{slug}/members")
def list_members(
    slug: Slug,
    principal: CurrentPrincipal,
    db: Db,
    limit: Limit = 50,
    offset: Offset = 0,
) -> MemberPage:
    org = service.load_organization(db, slug)
    require_member(db, org, principal.user.id)
    return membership.list_members(db, org, limit, offset)


@router.patch("/{slug}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def set_member_role(
    slug: Slug,
    user_id: Uuid7,
    payload: MemberRoleRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    org = service.load_organization(db, slug)
    require_owner(org, principal.user.id)
    membership.set_member_role(db, org, principal.user.id, user_id, payload.role)


@router.delete("/{slug}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    slug: Slug, user_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    org = service.load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    membership.remove_member(db, org, principal.user.id, user_id)


@router.get("/{slug}/applications")
def list_applications(
    slug: Slug,
    principal: CurrentPrincipal,
    db: Db,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ApplicationPage:
    org = service.load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    return membership.list_applications(db, org, limit, offset)


@router.post(
    "/{slug}/applications/{user_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
)
def approve_application(
    slug: Slug, user_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    org = service.load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    membership.approve_application(db, org, user_id)


@router.post(
    "/{slug}/applications/{user_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reject_application(
    slug: Slug, user_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    org = service.load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    membership.reject_application(db, org, user_id)
