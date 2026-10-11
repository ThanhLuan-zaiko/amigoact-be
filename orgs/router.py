"""HTTP layer for orgs: parsing, status codes, Depends. No business logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse

from core.config import Settings, get_settings
from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_media_service,
    get_media_store,
    get_org_service,
)
from core.exceptions import MediaTooLargeError, NotFoundError
from core.media import MEDIA_MIMES, media_kind
from orgs.interfaces import OrgContactDetails
from orgs.schemas import (
    BucketCount,
    CreateOrgRequest,
    MediaResponse,
    OrgListPage,
    OrgResponse,
    OrgSort,
    SetMediaRoleRequest,
    UpdateOrgRequest,
)

if TYPE_CHECKING:
    from core.media import LocalMediaStore
    from orgs.media_service import MediaService, MediaSnapshot
    from orgs.service import OrgService, OrgSnapshot

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
        join_policy=snapshot.join_policy,  # type: ignore[arg-type]
        email=snapshot.email,
        phone=snapshot.phone,
        website=snapshot.website,
        address=snapshot.address,
        city=snapshot.city,
        country=snapshot.country,
        legal_name=snapshot.legal_name,
        license_number=snapshot.license_number,
        is_personal=snapshot.is_personal,
        logo_media_id=snapshot.logo_media_id,
        cover_media_id=snapshot.cover_media_id,
        verified_at=snapshot.verified_at,
        previous_slug=snapshot.previous_slug,
        deleted_at=snapshot.deleted_at,
        created_at=snapshot.created_at,
    )


def _media_schema(item: MediaSnapshot) -> MediaResponse:
    return MediaResponse(
        id=item.id,
        org_id=item.org_id,
        kind=item.kind,  # type: ignore[arg-type]
        role=item.role,  # type: ignore[arg-type]
        mime=item.mime,
        size_bytes=item.size_bytes,
        file_url=item.file_url,
        uploader_id=item.uploader_id,
        original_name=item.original_name,
        upload_status=item.upload_status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Stream a multipart upload in 1MB chunks, capping the byte count."""
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
    return b"".join(parts)


def _contact_of(body: CreateOrgRequest | UpdateOrgRequest) -> OrgContactDetails:
    """Project the request's optional contact block into a value object."""
    return OrgContactDetails(
        email=body.email,
        phone=body.phone,
        website=body.website,
        address=body.address,
        city=body.city,
        country=body.country,
        legal_name=body.legal_name,
        license_number=body.license_number,
        is_personal=body.is_personal,
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
            body.join_policy,
            body.tax_code,
            body.legal_rep_name,
            body.legal_rep_id,
            body.legal_rep_position,
            _contact_of(body),
        )
    )


@router.get("/orgs/mine", response_model=OrgListPage)
def list_my_orgs(
    include_deleted: bool = Query(default=False),
    q: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=32),
    sort: OrgSort = Query(default="newest"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
) -> OrgListPage:
    """Search, filter, sort and page the orgs the current user owns or joined."""
    page = service.list_my_orgs(
        current.id,
        include_deleted,
        q=q,
        status=status,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return OrgListPage(
        items=[_org_schema(item) for item in page.items],
        total=page.total,
        counts=[BucketCount(bucket=key, count=count) for key, count in page.counts],
    )


@router.patch("/orgs/{org_id}", response_model=OrgResponse)
def update_org(
    org_id: UUID,
    body: UpdateOrgRequest,
    current: CurrentUser = Depends(get_current_user),
    service: OrgService = Depends(get_org_service),
) -> OrgResponse:
    """Owner renames, re-describes or re-policies a live org."""
    return _org_schema(
        service.update_org(
            org_id,
            current.id,
            body.name,
            body.description,
            body.join_policy,
            _contact_of(body),
        )
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
    role: Annotated[str, Form()] = "gallery",
    current: CurrentUser = Depends(get_current_user),
    service: MediaService = Depends(get_media_service),
    settings: Settings = Depends(get_settings),
) -> MediaResponse:
    """Member uploads one image/video; owner may flag cover/logo at once."""
    import asyncio

    guessed = media_kind(file.content_type or "application/octet-stream")
    max_mb = {
        "image": settings.media_max_image_mb,
        "video": settings.media_max_video_mb,
    }.get(guessed or "", max(settings.media_max_image_mb, settings.media_max_video_mb))
    content = await _read_limited(file, max_mb * 1024 * 1024)
    # Sync Pillow transcode plus disk write runs off the event loop.
    snapshot = await asyncio.to_thread(
        service.upload_media,
        org_id,
        current.id,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
        content,
        role,
    )
    return _media_schema(snapshot)


@router.put("/orgs/{org_id}/media/{media_id}/file", response_model=MediaResponse)
async def replace_org_media_file(
    org_id: UUID,
    media_id: UUID,
    file: UploadFile,
    current: CurrentUser = Depends(get_current_user),
    service: MediaService = Depends(get_media_service),
    settings: Settings = Depends(get_settings),
) -> MediaResponse:
    """Owner rewrites an image's bytes in place; id, role, URL stay put."""
    import asyncio

    content = await _read_limited(
        file, settings.media_max_image_mb * 1024 * 1024
    )
    snapshot = await asyncio.to_thread(
        service.replace_media,
        org_id,
        current.id,
        media_id,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
        content,
    )
    return _media_schema(snapshot)


@router.get("/orgs/{org_id}/media", response_model=list[MediaResponse])
def list_org_media(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: MediaService = Depends(get_media_service),
) -> list[MediaResponse]:
    """Newest-first gallery for members of a live org."""
    return [_media_schema(item) for item in service.list_media(org_id, current.id)]


@router.patch("/orgs/{org_id}/media/{media_id}", response_model=MediaResponse)
def set_org_media_role(
    org_id: UUID,
    media_id: UUID,
    body: SetMediaRoleRequest,
    current: CurrentUser = Depends(get_current_user),
    service: MediaService = Depends(get_media_service),
) -> MediaResponse:
    """Owner picks the cover/logo image; previous holder drops to gallery."""
    return _media_schema(
        service.set_media_role(org_id, current.id, media_id, body.role)
    )


@router.delete("/orgs/{org_id}/media", status_code=204)
def delete_all_org_media(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: MediaService = Depends(get_media_service),
) -> None:
    """Owner wipes the whole org gallery: metadata rows plus bytes."""
    service.delete_all_media(org_id, current.id)


@router.delete("/orgs/{org_id}/media/{media_id}", status_code=204)
def delete_org_media(
    org_id: UUID,
    media_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: MediaService = Depends(get_media_service),
) -> None:
    """Owner removes one gallery file: metadata row plus bytes."""
    service.delete_media(org_id, current.id, media_id)


@router.get("/media/{file_path:path}")
def serve_media_file(
    file_path: str, store: LocalMediaStore = Depends(get_media_store)
):
    """Semi-public uuid-guarded file serving (gallery photos are shared).

    Kept public for direct gallery rendering.
    TODO: switch galleries to short-lived signed URLs once available.
    """
    try:
        absolute = store.resolve(file_path)
    except ValueError as exc:
        raise NotFoundError("Media not found.") from exc
    if not absolute.is_file():
        raise NotFoundError("Media not found.")
    from pathlib import Path

    suffix = Path(absolute.name).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    mime = next((m for m, e in MEDIA_MIMES.items() if e == suffix), None)
    return FileResponse(
        str(absolute),
        media_type=mime or "application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )
