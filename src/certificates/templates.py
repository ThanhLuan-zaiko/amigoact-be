"""Certificate templates: the background picture and where each text goes."""

import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.certificates.template_schemas import (
    CertificateDesign,
    Layout,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
)
from src.media import service as media_service
from src.models.certificates import CertificateTemplate
from src.models.organizations import Organization


def list_templates(db: Session, org: Organization) -> list[CertificateTemplate]:
    """Inactive templates are listed too, so a manager can turn them back on."""
    return list(
        db.scalars(
            select(CertificateTemplate)
            .where(CertificateTemplate.org_id == org.id)
            .order_by(CertificateTemplate.created_at, CertificateTemplate.template_id)
        ).all()
    )


def _background(
    db: Session, asset_id: uuid.UUID | None, user_id: uuid.UUID
) -> uuid.UUID | None:
    if asset_id is None:
        return None
    return media_service.check_attachable(db, asset_id, user_id).asset_id


def create_template(
    db: Session, org: Organization, user_id: uuid.UUID, payload: TemplateCreate
) -> CertificateTemplate:
    template = CertificateTemplate(
        template_id=uuid.uuid7(),
        org_id=org.id,
        name=payload.name,
        background_media_id=_background(db, payload.background_asset_id, user_id),
        layout_json=payload.layout.model_dump(mode="json"),
        is_active=True,
    )
    db.add(template)
    db.commit()
    return template


def update_template(
    db: Session,
    template: CertificateTemplate,
    user_id: uuid.UUID,
    payload: TemplateUpdate,
) -> CertificateTemplate:
    if payload.name is not None:
        template.name = payload.name
    if "background_asset_id" in payload.model_fields_set:
        template.background_media_id = _background(
            db, payload.background_asset_id, user_id
        )
    if payload.layout is not None:
        template.layout_json = payload.layout.model_dump(mode="json")
    if payload.is_active is not None:
        template.is_active = payload.is_active
    db.commit()
    return template


def load_template(db: Session, template_id: uuid.UUID) -> CertificateTemplate:
    template = db.get(CertificateTemplate, template_id)
    if template is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "certificate_template_not_found")
    return template


def template_organization(db: Session, template: CertificateTemplate) -> Organization:
    org = db.get(Organization, template.org_id)
    if org is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "certificate_template_not_found")
    return org


def usable_template(
    db: Session, org_id: uuid.UUID, template_id: uuid.UUID
) -> CertificateTemplate:
    """Another organization's template looks like it does not exist."""
    template = load_template(db, template_id)
    if template.org_id != org_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "certificate_template_not_found")
    if not template.is_active:
        raise api_error(status.HTTP_409_CONFLICT, "certificate_template_inactive")
    return template


def _background_url(template: CertificateTemplate) -> str | None:
    background = template.background_media_id
    return f"/media/{background}/file" if background else None


def _layout(template: CertificateTemplate) -> Layout:
    return Layout.model_validate(template.layout_json or {})


def to_response(template: CertificateTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=template.template_id,
        name=template.name,
        is_active=template.is_active,
        background_url=_background_url(template),
        layout=_layout(template),
        created_at=template.created_at,
    )


def design_of(template: CertificateTemplate | None) -> CertificateDesign | None:
    """The look of an issued certificate. A template that was turned off later still
    counts, because a certificate keeps the template it was issued with."""
    if template is None:
        return None
    return CertificateDesign(
        background_url=_background_url(template), layout=_layout(template)
    )
