"""HTTP surface for certificates (thin router, rules in service)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from certificates.schemas import (
    CertificateResponse,
    MyCertificateResponse,
    RevokeBody,
    VerifyResponse,
)
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_features import get_certificate_service

if TYPE_CHECKING:
    from certificates.model import Certificate
    from certificates.service import CertificateService

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
    current: CurrentUser = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> CertificateResponse:
    """Issue a certificate for an attended registration."""
    return _response(
        service.issue(activity_id, student_id, current.id)
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


@router.get(
    "/certificates/verify/{serial_no}", response_model=VerifyResponse
)
def verify(
    serial_no: str,
    service: CertificateService = Depends(get_certificate_service),
) -> VerifyResponse:
    """Public serial verification — no auth required."""
    result = service.verify(serial_no)
    return VerifyResponse(
        serial_no=result.serial_no,
        status=result.status,
        activity_title=result.activity_title,
        student_name=result.student_name,
        issued_at=result.issued_at,  # type: ignore[arg-type]
    )
