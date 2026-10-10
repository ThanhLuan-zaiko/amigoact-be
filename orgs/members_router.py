"""Member endpoints: thin HTTP layer over MemberService."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_member_service,
)
from orgs.member_schemas import (
    BucketCount,
    InviteMemberRequest,
    MemberListPage,
    MemberResponse,
    MembershipPage,
    MyMembership,
    UpdateMemberRequest,
)
from orgs.member_listing import MemberSnapshot
from orgs.member_service import MemberService

router = APIRouter(tags=["orgs"])



def _to_member(row: MemberSnapshot) -> MemberResponse:
    return MemberResponse(
        user_id=row.user_id,
        org_id=row.org_id,
        full_name=row.full_name,
        email=row.email,
        role=row.role,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        joined_at=row.joined_at,
    )


@router.get(
    "/orgs/memberships/mine",
    response_model=MembershipPage,
    status_code=status.HTTP_200_OK,
)
def list_my_memberships(
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
    membership_status: str | None = Query(
        None, alias="status", max_length=20
    ),
) -> MembershipPage:
    """List the caller's membership links (invitation inbox, all orgs)."""
    items = service.list_my_memberships(
        current_user.id, status=membership_status
    )
    return MembershipPage(
        items=[
            MyMembership(
                org_id=item.org_id,
                org_name=item.org_name,
                org_slug=item.org_slug,
                role=item.role,  # type: ignore[arg-type]
                status=item.status,  # type: ignore[arg-type]
                joined_at=item.joined_at,
            )
            for item in items
        ],
        total=len(items),
    )


@router.get(
    "/orgs/{org_id}/members",
    response_model=MemberListPage,
    status_code=status.HTTP_200_OK,
)
def list_members(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
    q: str | None = Query(None, max_length=80),
    member_status: str | None = Query(
        None, alias="status", max_length=20
    ),
    sort: str = Query("newest", max_length=20),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> MemberListPage:
    """List one org's roster (members only; managers see every state)."""
    page = service.list_members(
        org_id,
        current_user.id,
        q=q,
        status=member_status,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return MemberListPage(
        items=[_to_member(item) for item in page.items],
        total=page.total,
        counts=[
            BucketCount(bucket=key, count=count)
            for key, count in page.counts
        ],
        viewer_role=page.viewer_role,  # type: ignore[arg-type]
    )


@router.post(
    "/orgs/{org_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    org_id: UUID,
    body: InviteMemberRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Owner/admin invites an account by email (status invited)."""
    row = service.invite_member(
        org_id, current_user.id, body.email, role=body.role
    )
    return _to_member(row)


@router.patch(
    "/orgs/{org_id}/members/{user_id}",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
)
def update_member(
    org_id: UUID,
    user_id: UUID,
    body: UpdateMemberRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Assign a role (owner) or suspend/reactivate (owner/admin)."""
    row = service.update_member(
        org_id,
        current_user.id,
        user_id,
        role=body.role,
        status=body.status,
    )
    return _to_member(row)


@router.delete(
    "/orgs/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def remove_member(
    org_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> Response:
    """Manager removes a member, or the member leaves; status left."""
    service.remove_member(org_id, current_user.id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/orgs/{org_id}/members/join",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def join_org(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Join an open org instantly; invite orgs return 403."""
    row = service.join_org(org_id, current_user.id)
    return _to_member(row)


@router.post(
    "/orgs/{org_id}/members/me/accept",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
)
def accept_invitation(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Invitee accepts: invited to active."""
    row = service.accept_invitation(org_id, current_user.id)
    return _to_member(row)


@router.post(
    "/orgs/{org_id}/members/me/decline",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
)
def decline_invitation(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Invitee declines: invited to left (audit kept)."""
    row = service.decline_invitation(org_id, current_user.id)
    return _to_member(row)
