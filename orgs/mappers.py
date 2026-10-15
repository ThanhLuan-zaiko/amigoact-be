"""Snapshot -> response and request -> value-object mappers for the orgs API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from orgs.interfaces import OrgContactDetails, OrgLegalEdit
from orgs.schemas import (
    CreateOrgRequest,
    MediaResponse,
    OrgResponse,
    UpdateOrgRequest,
)

if TYPE_CHECKING:
    from orgs.media_service import MediaSnapshot
    from orgs.service import OrgSnapshot

_LEGAL_KEYS = frozenset(
    {"tax_code", "legal_rep_name", "legal_rep_id", "legal_rep_position"}
)


def org_schema(snapshot: OrgSnapshot) -> OrgResponse:
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


def media_schema(item: MediaSnapshot) -> MediaResponse:
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


def legal_of(body: UpdateOrgRequest) -> OrgLegalEdit | None:
    """Project explicitly sent legal fields; absent keys keep old values."""
    provided = body.model_fields_set & _LEGAL_KEYS
    if not provided:
        return None
    return OrgLegalEdit(
        tax_code=body.tax_code,
        legal_rep_name=body.legal_rep_name,
        legal_rep_id=body.legal_rep_id,
        legal_rep_position=body.legal_rep_position,
        provided=frozenset(provided),
    )


def contact_of(body: CreateOrgRequest | UpdateOrgRequest) -> OrgContactDetails:
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
