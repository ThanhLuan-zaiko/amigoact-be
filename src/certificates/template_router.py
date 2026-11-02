"""Routes for managing certificate templates."""

from typing import Annotated

from fastapi import APIRouter, Path, status

from src.auth.deps import CurrentPrincipal, Db
from src.certificates import templates
from src.certificates.template_schemas import (
    TemplateCreate,
    TemplateList,
    TemplateResponse,
    TemplateUpdate,
)
from src.organizations.access import require_manager
from src.organizations.service import load_organization
from src.validation import Uuid7

router = APIRouter(tags=["certificates"])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]


@router.post(
    "/organizations/{slug}/certificate-templates",
    status_code=status.HTTP_201_CREATED,
)
def create_template(
    slug: Slug, payload: TemplateCreate, principal: CurrentPrincipal, db: Db
) -> TemplateResponse:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    template = templates.create_template(db, org, principal.user.id, payload)
    return templates.to_response(template)


@router.get("/organizations/{slug}/certificate-templates")
def list_templates(slug: Slug, principal: CurrentPrincipal, db: Db) -> TemplateList:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    rows = templates.list_templates(db, org)
    return TemplateList(items=[templates.to_response(row) for row in rows])


@router.patch("/certificate-templates/{template_id}")
def update_template(
    template_id: Uuid7,
    payload: TemplateUpdate,
    principal: CurrentPrincipal,
    db: Db,
) -> TemplateResponse:
    template = templates.load_template(db, template_id)
    org = templates.template_organization(db, template)
    require_manager(db, org, principal.user.id)
    template = templates.update_template(db, template, principal.user.id, payload)
    return templates.to_response(template)
