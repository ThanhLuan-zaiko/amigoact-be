"""Routes for certificates."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from src.activities import service as activity_service
from src.auth.deps import CurrentPrincipal, Db
from src.certificates import service, templates
from src.certificates.schemas import (
    ActivityCertificates,
    IssueRequest,
    IssueResult,
    MyCertificate,
    RevokeRequest,
    VerifiedCertificate,
)
from src.notifications.delivery import deliver_emails
from src.validation import Uuid7

router = APIRouter(tags=["certificates"], dependencies=[Depends(deliver_emails)])

Serial = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{5,40}$")]


@router.post("/activities/{activity_id}/certificates")
def issue_certificates(
    activity_id: Uuid7,
    principal: CurrentPrincipal,
    db: Db,
    payload: IssueRequest | None = None,
) -> IssueResult:
    activity = activity_service.load_activity(db, activity_id, lock=True)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    template_id = None
    if payload is not None and payload.template_id is not None:
        template = templates.usable_template(db, activity.org_id, payload.template_id)
        template_id = template.template_id
    return service.issue_certificates(db, activity, principal.user.id, template_id)


@router.get("/activities/{activity_id}/certificates")
def activity_certificates(
    activity_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> ActivityCertificates:
    activity = activity_service.load_activity(db, activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    return service.activity_certificates(db, activity.id)


@router.get("/certificates/mine")
def my_certificates(principal: CurrentPrincipal, db: Db) -> list[MyCertificate]:
    return service.my_certificates(db, principal.user.id)


@router.get("/certificates/verify/{serial}")
def verify_certificate(serial: Serial, db: Db) -> VerifiedCertificate:
    return service.verify_certificate(db, serial)


@router.post(
    "/certificates/{certificate_id}/revoke", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_certificate(
    certificate_id: Uuid7,
    payload: RevokeRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    certificate = service.load_certificate(db, certificate_id)
    activity = activity_service.load_activity(db, certificate.activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    service.revoke_certificate(db, certificate, principal.user.id, payload.reason)


@router.post(
    "/certificates/{certificate_id}/reinstate",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reinstate_certificate(
    certificate_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    certificate = service.load_certificate(db, certificate_id)
    activity = activity_service.load_activity(db, certificate.activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    service.reinstate_certificate(db, certificate)
