"""HTTP surface for certificates (thin router, rules in service)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from certificates.schemas import (
    CertificateResponse,
    IssueBody,
    MyCertificateResponse,
    RevokeBody,
    TemplateBody,
    TemplatePatchBody,
    TemplateResponse,
    VerifyResponse,
)
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_certificates import (
    get_certificate_file_service,
    get_certificate_service,
    get_template_service,
)

if TYPE_CHECKING:
    from certificates.file_service import CertificateFileService
    from certificates.model import Certificate, CertificateTemplate
    from certificates.service import CertificateService
    from certificates.template_service import TemplateService

router = APIRouter(tags=["certificates"])


def _response(row: Certificate) -> CertificateResponse:
    return CertificateResponse(
        certificate_id=row.certificate_id,
        activity_id=row.activity_id,
        student_id=row.student_id,
        serial_no=row.serial_no,
        status=row.status,
        issued_at=row.issued_at,
    )


@router.post(
    "/activities/{activity_id}/certificates/{student_id}",
    response_model=CertificateResponse,
    status_code=201,
)
def issue(
    activity_id: UUID,
    student_id: UUID,
    body: IssueBody | None = None,
    current: CurrentUser = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> CertificateResponse:
    """Issue a certificate for an attended registration."""
    return _response(
        service.issue(
            activity_id, student_id, current.id,
            body.template_id if body else None,
        )
    )


@router.post(
    "/activities/{activity_id}/certificates/{student_id}/revoke",
    response_model=CertificateResponse,
)
def revoke(
    activity_id: UUID,
    student_id: UUID,
    body: RevokeBody,
    current: CurrentUser = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> CertificateResponse:
    """Revoke keeps the row but flips status everywhere."""
    return _response(
        service.revoke(
            activity_id, student_id, current.id, body.reason
        )
    )


@router.get(
    "/activities/{activity_id}/certificates",
    response_model=list[CertificateResponse],
)
def activity_certificates(
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> list[CertificateResponse]:
    """Manager listing so the roster can surface issued/revoked state."""
    return [
        _response(row)
        for row in service.for_activity(activity_id, current.id)
    ]


@router.get(
    "/certificates/mine",
    response_model=list[MyCertificateResponse],
)
def my_certificates(
    current: CurrentUser = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> list[MyCertificateResponse]:
    """The caller's certificate wall."""
    return [
        MyCertificateResponse(
            certificate_id=item.certificate.certificate_id,
            activity_id=item.certificate.activity_id,
            activity_title=item.activity_title,
            serial_no=item.certificate.serial_no,
            status=item.certificate.status,
            issued_at=item.certificate.issued_at,
        )
        for item in service.mine(current.id)
    ]


@router.get("/certificates/{certificate_id}/file")
def download_file(
    certificate_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: "CertificateFileService" = Depends(
        get_certificate_file_service
    ),
) -> Response:
    """Stream the certificate PDF; rendered lazily on first download."""
    blob = service.download(certificate_id, current.id)
    return Response(
        content=blob.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{blob.filename}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/certificates/verify/{serial_no}", response_model=VerifyResponse
)
def verify(
    serial_no: str,
    service: CertificateService = Depends(get_certificate_service),
) -> VerifyResponse:
    """Public serial verification - no auth required."""
    result = service.verify(serial_no)
    return VerifyResponse(
        serial_no=result.serial_no,
        status=result.status,
        activity_title=result.activity_title,
        student_name=result.student_name,
        issued_at=result.issued_at,  # type: ignore[arg-type]
    )


def _template(row: CertificateTemplate) -> TemplateResponse:
    return TemplateResponse(
        template_id=row.template_id,
        org_id=row.org_id,
        name=row.name,
        background_media_id=row.background_media_id,
        layout_json=row.layout_json,
        is_active=row.is_active,
        created_at=row.created_at,
    )


@router.get(
    "/orgs/{org_id}/certificate-templates",
    response_model=list[TemplateResponse],
)
def list_templates(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: TemplateService = Depends(get_template_service),
) -> list[TemplateResponse]:
    """Manager reads the org's certificate template library."""
    return [
        _template(t) for t in service.list(org_id, current.id)
    ]


@router.post(
    "/orgs/{org_id}/certificate-templates",
    response_model=TemplateResponse,
    status_code=201,
)
def create_template(
    org_id: UUID,
    body: TemplateBody,
    current: CurrentUser = Depends(get_current_user),
    service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """Register a background/layout pair for certificate issuance."""
    return _template(
        service.create(
            org_id, current.id, body.name,
            body.background_media_id, body.layout_json,
        )
    )


@router.patch(
    "/orgs/{org_id}/certificate-templates/{template_id}",
    response_model=TemplateResponse,
)
def update_template(
    org_id: UUID,
    template_id: UUID,
    body: TemplatePatchBody,
    current: CurrentUser = Depends(get_current_user),
    service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """Patch name/background/layout or toggle active."""
    return _template(
        service.update(
            org_id, template_id, current.id, body.name,
            body.background_media_id, body.layout_json, body.is_active,
        )
    )
