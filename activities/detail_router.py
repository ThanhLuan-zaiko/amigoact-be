"""HTTP layer for activity detail edges and the composed detail page."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from activities.router import _response, _summary
from activities.schemas import (
    ActivityDetailResponse,
    ActivitySummary,
    AnnouncementBody,
    AnnouncementItem,
    FormQuestionItem,
    PartnerDetail,
    ScheduleBody,
    ScheduleItem,
    SetFormBody,
    SetPartnersBody,
    SetSkillsBody,
    SetStaffBody,
    SkillEdgeDetail,
    StaffDetail,
)
from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_optional_user,
)
from core.dependencies_features import get_activity_detail_service
from core.dependencies_workspace import get_form_service

if TYPE_CHECKING:
    from activities.detail_service import (
        ActivityDetail,
        ActivityDetailService,
    )
    from activities.form_service import FormService

router = APIRouter(tags=["activities"])


def _detail_response(detail: ActivityDetail) -> ActivityDetailResponse:
    return ActivityDetailResponse(
        activity=_response(detail.activity),
        skills=[
            SkillEdgeDetail(
                skill_id=edge.skill_id,
                name=edge.name,
                slug=edge.slug,
                is_required=edge.is_required,
            )
            for edge in detail.skills
        ],
        partners=[
            PartnerDetail(
                org_id=edge.org_id,
                name=edge.name,
                role=edge.role,
                note=edge.note,
            )
            for edge in detail.partners
        ],
        staff=[
            StaffDetail(
                user_id=row.user_id,
                full_name=row.full_name,
                staff_role=row.staff_role,
                assigned_at=row.assigned_at,
            )
            for row in detail.staff
        ],
        schedules=[
            ScheduleItem(
                id=row.id,
                title=row.title,
                location=row.location,
                start_at=row.start_at,
                end_at=row.end_at,
                status=row.status,
            )
            for row in detail.schedules
        ],
        announcements=[
            AnnouncementItem(
                announcement_id=row.announcement_id,
                title=row.title,
                body=row.body or "",
                published_at=row.published_at,
            )
            for row in detail.announcements
        ],
    )


@router.get(
    "/orgs/{org_id}/activities/{activity_id}/detail",
    response_model=ActivityDetailResponse,
)
def get_activity_detail(
    org_id: UUID,
    activity_id: UUID,
    viewer: CurrentUser | None = Depends(get_optional_user),
    service: ActivityDetailService = Depends(get_activity_detail_service),
) -> ActivityDetailResponse:
    """Composed detail: row plus skills, partners, staff, sessions."""
    return _detail_response(
        service.detail(
            org_id, activity_id, viewer.id if viewer else None
        )
    )


@router.put(
    "/orgs/{org_id}/activities/{activity_id}/skills",
    response_model=ActivityDetailResponse,
)
def set_activity_skills(
    org_id: UUID,
    activity_id: UUID,
    body: SetSkillsBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityDetailService = Depends(get_activity_detail_service),
) -> ActivityDetailResponse:
    """Managers replace the required/desired skill edges."""
    return _detail_response(
        service.set_skills(
            org_id,
            activity_id,
            current.id,
            [(edge.skill_id, edge.is_required) for edge in body.skills],
        )
    )


@router.put(
    "/orgs/{org_id}/activities/{activity_id}/partners",
    response_model=ActivityDetailResponse,
)
def set_activity_partners(
    org_id: UUID,
    activity_id: UUID,
    body: SetPartnersBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityDetailService = Depends(get_activity_detail_service),
) -> ActivityDetailResponse:
    """Managers replace partner orgs with co_organizer|sponsor roles."""
    return _detail_response(
        service.set_partners(
            org_id,
            activity_id,
            current.id,
            [
                (edge.org_id, edge.role, edge.note)
                for edge in body.partners
            ],
        )
    )


@router.put(
    "/orgs/{org_id}/activities/{activity_id}/staff",
    response_model=ActivityDetailResponse,
)
def set_activity_staff(
    org_id: UUID,
    activity_id: UUID,
    body: SetStaffBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityDetailService = Depends(get_activity_detail_service),
) -> ActivityDetailResponse:
    """Managers replace staff; every assignee must be an org member."""
    return _detail_response(
        service.set_staff(
            org_id,
            activity_id,
            current.id,
            [(row.user_id, row.staff_role) for row in body.staff],
        )
    )


@router.post(
    "/orgs/{org_id}/activities/{activity_id}/schedules",
    response_model=ActivityDetailResponse,
    status_code=201,
)
def add_schedule(
    org_id: UUID,
    activity_id: UUID,
    body: ScheduleBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityDetailService = Depends(get_activity_detail_service),
) -> ActivityDetailResponse:
    """Managers append one session to the activity."""
    return _detail_response(
        service.add_schedule(
            org_id,
            activity_id,
            current.id,
            body.title,
            body.location,
            body.start_at,
            body.end_at,
        )
    )


@router.delete(
    "/orgs/{org_id}/activities/{activity_id}/schedules/{schedule_id}",
    response_model=ActivityDetailResponse,
)
def remove_schedule(
    org_id: UUID,
    activity_id: UUID,
    schedule_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityDetailService = Depends(get_activity_detail_service),
) -> ActivityDetailResponse:
    """Managers remove one session from the activity."""
    return _detail_response(
        service.delete_schedule(
            org_id, activity_id, schedule_id, current.id
        )
    )


@router.post(
    "/orgs/{org_id}/activities/{activity_id}/announcements",
    response_model=ActivityDetailResponse,
    status_code=201,
)
def add_announcement(
    org_id: UUID,
    activity_id: UUID,
    body: AnnouncementBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityDetailService = Depends(get_activity_detail_service),
) -> ActivityDetailResponse:
    """Managers post one item onto the activity news board."""
    return _detail_response(
        service.add_announcement(
            org_id, activity_id, current.id, body.title, body.body
        )
    )


def _form_response(rows) -> list[FormQuestionItem]:  # noqa: ANN001, ANN202
    return [
        FormQuestionItem(
            question_id=q.question_id,
            label=q.label,
            field_type=q.field_type,
            required=q.required,
        )
        for q in rows
    ]


@router.get(
    "/orgs/{org_id}/activities/{activity_id}/form",
    response_model=list[FormQuestionItem],
)
def get_form(
    org_id: UUID,
    activity_id: UUID,
    viewer: CurrentUser | None = Depends(get_optional_user),
    service: FormService = Depends(get_form_service),
) -> list[FormQuestionItem]:
    """Sign-up form; public while registration is open."""
    return _form_response(
        service.get_form(
            org_id, activity_id, viewer.id if viewer else None
        )
    )


@router.put(
    "/orgs/{org_id}/activities/{activity_id}/form",
    response_model=list[FormQuestionItem],
)
def set_form(
    org_id: UUID,
    activity_id: UUID,
    body: SetFormBody,
    current: CurrentUser = Depends(get_current_user),
    service: FormService = Depends(get_form_service),
) -> list[FormQuestionItem]:
    """Managers replace the sign-up form questions."""
    return _form_response(
        service.set_form(
            org_id,
            activity_id,
            current.id,
            [(q.label, q.field_type, q.required) for q in body.questions],
        )
    )


@router.get(
    "/orgs/{org_id}/partners/activities",
    response_model=list[ActivitySummary],
)
def partner_feed(
    org_id: UUID,
    service: ActivityDetailService = Depends(get_activity_detail_service),
) -> list[ActivitySummary]:
    """Public feed of activities the org partners on."""
    return [_summary(row) for row in service.partner_feed(org_id)]
