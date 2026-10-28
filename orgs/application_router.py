"""Membership application endpoints: form editing, apply, review, read-back."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from core.dependencies import CurrentUser, get_current_user, get_member_service
from orgs.application_schemas import (
    ApplicationAnswer,
    ApplicationResponse,
    ApplyRequest,
    MembershipFormBody,
    MembershipFormResponse,
    MembershipQuestion,
)
from orgs.member_schemas import MemberResponse
from orgs.member_service import MemberService
from orgs.members_router import _to_member

router = APIRouter(tags=["orgs"])


def _form_response(rows) -> MembershipFormResponse:  # noqa: ANN001
    return MembershipFormResponse(
        questions=[
            MembershipQuestion(
                question_id=row.question_id,
                label=row.label,
                field_type=row.field_type,
                required=row.required,
            )
            for row in rows
        ]
    )


@router.get(
    "/orgs/{org_id}/membership-form",
    response_model=MembershipFormResponse,
    status_code=status.HTTP_200_OK,
)
def get_membership_form(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MembershipFormResponse:
    """Questions an applicant answers; any signed-in viewer may read them."""
    return _form_response(service.list_membership_form(org_id))


@router.put(
    "/orgs/{org_id}/membership-form",
    response_model=MembershipFormResponse,
    status_code=status.HTTP_200_OK,
)
def replace_membership_form(
    org_id: UUID,
    body: MembershipFormBody,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MembershipFormResponse:
    """Managers replace the whole form; existing applications keep their answers."""
    rows = service.replace_membership_form(
        org_id,
        current_user.id,
        [(q.label, q.field_type, q.required) for q in body.questions],
    )
    return _form_response(rows)


@router.post(
    "/orgs/{org_id}/members/apply",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_to_org(
    org_id: UUID,
    body: ApplyRequest,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Submit the form for review; the row becomes applied until a manager decides."""
    snapshot = service.apply_to_org(org_id, current_user.id, body.answers)
    response.headers["Location"] = f"/orgs/{org_id}/members/{current_user.id}"
    return _to_member(snapshot)


@router.get(
    "/orgs/{org_id}/members/{user_id}/application",
    response_model=ApplicationResponse,
    status_code=status.HTTP_200_OK,
)
def read_application(
    org_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> ApplicationResponse:
    """Reviewer reads one submission against the current form questions."""
    stored, questions = service.get_application(org_id, current_user.id, user_id)
    answers = json.loads(stored.answers or "{}")
    return ApplicationResponse(
        user_id=stored.user_id,
        submitted_at=stored.submitted_at,
        answers=[
            ApplicationAnswer(
                question_id=question.question_id,
                label=question.label,
                answer=str(answers.get(str(question.question_id), "")),
            )
            for question in questions
        ],
    )


@router.post(
    "/orgs/{org_id}/members/{user_id}/approve",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
)
def approve_application(
    org_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Manager accepts a pending application: applied -> active."""
    snapshot = service.review_application(
        org_id, current_user.id, user_id, approve=True
    )
    return _to_member(snapshot)


@router.post(
    "/orgs/{org_id}/members/{user_id}/reject",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
)
def reject_application(
    org_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Manager declines a pending application: applied -> left, may re-apply."""
    snapshot = service.review_application(
        org_id, current_user.id, user_id, approve=False
    )
    return _to_member(snapshot)
