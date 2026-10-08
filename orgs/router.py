"""HTTP layer for orgs: parsing, status codes, Depends. No business logic."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, UploadFile
from fastapi.responses import FileResponse

from core.config import Settings, get_settings
from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_media_store,
    get_org_service,
)
from core.exceptions import NotFoundError
from orgs.schemas import CreateOrgRequest, MediaResponse, OrgResponse, UpdateOrgRequest

if TYPE_CHECKING:
    from core.media import LocalMediaStore
    from orgs.service import MediaSnapshot, OrgService, OrgSnapshot

router = APIRouter(tags=["orgs"])


def _org_schema(snapshot: OrgSnapshot) -> OrgResponse:
    return OrgResponse(
        id=snapshot.id,
        name=snapshot.name,
        slug=snapshot.slug,
        description=snapshot.description,
        kind=snapshot.kind,  # type: ignore[arg-type]
        member_count=snapshot.member_count,
        event_count=0,
        owner_id=snapshot.owner_id,
        tax_code=snapshot.tax_code,
        legal_rep_name=snapshot.legal_rep_name,
        legal_rep_id=snapshot.legal_rep_id,
        legal_rep_position=snapshot.legal_rep_position,
        legal_status=snapshot.legal_status,
        status=snapshot.status,
        deleted_at=snapshot.deleted_at,
        created_at=snapshot.created_at,
    )


def _media_schema(item: MediaSnapshot) -> MediaResponse:
    return MediaResponse(
        id=item.id,
        org_id=item.org_id,
        kind=item.kind,  # type: ignore[arg-type]
        mime=item.mime,
        size_bytes=item.size_bytes,
        file_url=item.file_url,
        created_at=item.created_at,
    )


@router.post("/orgs", response_model=OrgResponse, status_code=201)
def create_org(
    body: CreateOrgRequest,
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
) -> OrgResponse:
    """Create an org. The caller becomes owner; business needs legal head."""
    return _org_schema(
        service.create_org(
            current.id,
            body.name,
            body.slug,
            body.description,
            body.kind,
            body.tax_code,
            body.legal_rep_name,
            body.legal_rep_id,
            body.legal_rep_position,
        )
    )


@router.get("/orgs/mine", response_model=list[OrgResponse])
def list_my_orgs(
    include_deleted: bool = Query(default=False),
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
) -> list[OrgResponse]:
    """List orgs the current user owns or joined (trash on request)."""
    return [
        _org_schema(item)
        for item in service.list_my_orgs(current.id, include_deleted)
    ]


@router.patch("/orgs/{org_id}", response_model=OrgResponse)
def update_org(
    org_id: UUID,
    body: UpdateOrgRequest,
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
) -> OrgResponse:
    """Owner renames or re-describes a live org."""
    return _org_schema(
        service.update_org(org_id, current.id, body.name, body.description)
    )


@router.delete("/orgs/{org_id}", response_model=OrgResponse | None, status_code=200)
def delete_org(
    org_id: UUID,
    hard: bool = Query(default=False),
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
):
    """Soft delete to trash by default; hard=true erases rows and files."""
    if hard:
        service.hard_delete_org(org_id, current.id)
        return Response(status_code=204)
    return _org_schema(service.soft_delete_org(org_id, current.id))


@router.post("/orgs/{org_id}/restore", response_model=OrgResponse)
def restore_org(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
) -> OrgResponse:
    """Owner brings a soft-deleted org back to the visible list."""
    return _org_schema(service.restore_org(org_id, current.id))


@router.post("/orgs/{org_id}/media", response_model=MediaResponse, status_code=201)
async def upload_org_media(
    org_id: UUID,
    file: UploadFile,
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
    settings: Settings = Depends(get_settings),
) -> MediaResponse:
    """Member uploads one image/video. Reads are capped past the max limit."""
    cap = max(settings.media_max_image_mb, settings.media_max_video_mb) * 1024 * 1024
    content = await file.read(cap + 1)
    return _media_schema(
        service.upload_media(
            org_id, current.id, file.filename or "upload",
            file.content_type or "application/octet-stream", content,
        )
    )


@router.get("/orgs/{org_id}/media", response_model=list[MediaResponse])
def list_org_media(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
) -> list[MediaResponse]:
    """Newest-first gallery for members of a live org."""
    return [_media_schema(item) for item in service.list_media(org_id, current.id)]


@router.delete("/orgs/{org_id}/media/{media_id}", status_code=204)
def delete_org_media(
    org_id: UUID,
    media_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
) -> None:
    """Owner removes one gallery file: metadata row plus bytes."""
    service.delete_media(org_id, current.id, media_id)


@router.get("/media/{file_path:path}")
def serve_media_file(
    file_path: str, store: LocalMediaStore = Depends(get_media_store)
):
    """Public uuid-guarded file serving (gallery photos are semi-public)."""
    try:
        absolute = store.resolve(file_path)
    except ValueError as exc:
        raise NotFoundError("Media not found.") from exc
    if not absolute.is_file():
        raise NotFoundError("Media not found.")
    return FileResponse(str(absolute))
