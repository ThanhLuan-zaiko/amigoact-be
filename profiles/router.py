"""HTTP layer for volunteer profiles: parsing and status codes only."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile

from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_settings,
)
from core.dependencies_features import get_profile_service
from core.exceptions import MediaTooLargeError
from profiles.schemas import (
    AvatarResponse,
    ContactCreate,
    ContactItem,
    ProfileBody,
    ProfileResponse,
    PublicProfileResponse,
    SetSkillsBody,
    SkillEdgeItem,
    SkillItem,
)

if TYPE_CHECKING:
    from core.config import Settings
    from profiles.service import ProfileBundle, ProfileService, PublicCard

router = APIRouter(tags=["profiles"])


def _edge_item(edge) -> SkillEdgeItem:  # noqa: ANN001, ANN202
    return SkillEdgeItem(
        id=edge.skill_id, name=edge.name, slug=edge.slug, level=edge.level
    )


def _contact_item(row) -> ContactItem:  # noqa: ANN001, ANN202
    return ContactItem(
        contact_id=row.contact_id,
        name=row.name,
        relation=row.relation,
        phone=row.phone,
        is_primary=bool(row.is_primary),
    )


def _profile_response(bundle: ProfileBundle) -> ProfileResponse:
    profile = bundle.profile
    return ProfileResponse(
        student_code=getattr(profile, "student_code", None),
        campus_id=getattr(profile, "campus_id", None),
        department_id=getattr(profile, "department_id", None),
        class_name=getattr(profile, "class_name", None),
        enrollment_year=getattr(profile, "enrollment_year", None),
        school_name=getattr(profile, "school_name", None),
        bio=getattr(profile, "bio", None),
        interests=sorted(getattr(profile, "interests", None) or []),
        status=getattr(profile, "status", None),
        total_hours=float(getattr(profile, "total_hours", 0.0) or 0.0),
        updated_at=getattr(profile, "updated_at", None),
        skills=[_edge_item(edge) for edge in bundle.skills],
        contacts=[_contact_item(row) for row in bundle.contacts],
        avatar_url=bundle.avatar_url,
    )


def _public_response(card: PublicCard) -> PublicProfileResponse:
    profile = card.profile
    return PublicProfileResponse(
        full_name=card.full_name,
        school_name=getattr(profile, "school_name", None),
        class_name=getattr(profile, "class_name", None),
        bio=getattr(profile, "bio", None),
        interests=sorted(getattr(profile, "interests", None) or []),
        total_hours=float(getattr(profile, "total_hours", 0.0) or 0.0),
        skills=[_edge_item(edge) for edge in card.skills],
        avatar_url=card.avatar_url,
        member_since=card.member_since,
    )


@router.get("/skills", response_model=list[SkillItem])
def list_skills(
    service: ProfileService = Depends(get_profile_service),
) -> list[SkillItem]:
    """Public skill catalog for pickers and matching screens."""
    return [
        SkillItem(id=row.id, name=row.name, slug=row.slug)
        for row in service.list_catalog()
    ]


@router.get("/profiles/me", response_model=ProfileResponse)
def get_my_profile(
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    """Own profile bundle: fields, skills, contacts, avatar."""
    return _profile_response(service.get_mine(current.id))


@router.put("/profiles/me", response_model=ProfileResponse)
def update_my_profile(
    body: ProfileBody,
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    """Full replace of the editable profile fields."""
    return _profile_response(
        service.update_mine(
            current.id,
            student_code=body.student_code,
            campus_id=body.campus_id,
            department_id=body.department_id,
            class_name=body.class_name,
            enrollment_year=body.enrollment_year,
            school_name=body.school_name,
            bio=body.bio,
            interests=set(body.interests),
            status=body.status,
        )
    )


@router.put("/profiles/me/skills", response_model=ProfileResponse)
def set_my_skills(
    body: SetSkillsBody,
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    """Replace the whole skill set (validated against the catalog)."""
    edges = [(edge.skill_id, edge.level) for edge in body.skills]
    return _profile_response(service.set_skills(current.id, edges))


@router.post(
    "/profiles/me/contacts",
    response_model=ProfileResponse,
    status_code=201,
)
def add_my_contact(
    body: ContactCreate,
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    """Append one emergency contact (three max, first is primary)."""
    return _profile_response(
        service.add_contact(
            current.id,
            name=body.name,
            relation=body.relation,
            phone=body.phone,
            is_primary=body.is_primary,
        )
    )


@router.delete(
    "/profiles/me/contacts/{contact_id}", response_model=ProfileResponse
)
def remove_my_contact(
    contact_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    """Delete one emergency contact; newest survivor turns primary."""
    return _profile_response(
        service.remove_contact(current.id, contact_id)
    )


@router.post("/profiles/me/avatar", response_model=AvatarResponse)
async def upload_my_avatar(
    file: UploadFile,
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
    settings: Settings = Depends(get_settings),
) -> AvatarResponse:
    """Upload one image; replaces the old avatar asset when present."""
    import asyncio

    limit = settings.media_max_image_mb * 1024 * 1024
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise MediaTooLargeError("File exceeds the size limit.")
        parts.append(chunk)
    url = await asyncio.to_thread(
        service.upload_avatar,
        current.id,
        file.filename or "avatar",
        file.content_type or "application/octet-stream",
        b"".join(parts),
    )
    return AvatarResponse(avatar_url=url)


@router.get(
    "/profiles/{user_id}", response_model=PublicProfileResponse
)
def get_public_profile(
    user_id: UUID,
    service: ProfileService = Depends(get_profile_service),
) -> PublicProfileResponse:
    """Public volunteer card; no auth, no PII beyond display fields."""
    return _public_response(service.public_card(user_id))
