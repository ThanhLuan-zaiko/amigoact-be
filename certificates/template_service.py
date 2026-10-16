"""Certificate template CRUD scoped to one org."""

from __future__ import annotations

import json
from uuid import UUID

from certificates.interfaces import TemplateStore
from certificates.model import CertificateTemplate
from core.exceptions import (
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from core.ids import uuid7
from core.security import utcnow
from orgs.interfaces import OrgRepository
from rbac.interfaces import AccessControl


class TemplateService:
    """Manager CRUD over the org's small template library."""

    def __init__(
        self,
        templates: TemplateStore,
        orgs: OrgRepository,
        access: AccessControl,
    ) -> None:
        self._templates = templates
        self._orgs = orgs
        self._access = access

    def _require_manager(
        self, org_id: UUID, actor: UUID, action: str
    ) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if (
            getattr(org, "owner_id", None) != actor
            and not self._access.has_permission(
                org_id, actor, "activity:manage"
            )
        ):
            self._access.record(
                org_id, actor, action, "certificate_template",
                None, "denied",
            )
            raise ForbiddenError("Only org managers can do this.")

    @staticmethod
    def _valid_layout(layout_json: str | None) -> None:
        if layout_json is None:
            return
        try:
            parsed = json.loads(layout_json)
        except (TypeError, ValueError) as exc:
            raise InvalidRegistrationStateError(
                "Layout must be valid JSON."
            ) from exc
        if not isinstance(parsed, dict):
            raise InvalidRegistrationStateError(
                "Layout JSON must be an object."
            )

    def list(
        self, org_id: UUID, actor: UUID
    ) -> list[CertificateTemplate]:
        """Manager reads the library, newest first."""
        self._require_manager(org_id, actor, "template.list")
        return sorted(
            self._templates.list_by_org(org_id),
            key=lambda t: t.created_at or 0,
            reverse=True,
        )

    def create(
        self,
        org_id: UUID,
        actor: UUID,
        name: str,
        background_media_id: UUID | None = None,
        layout_json: str | None = None,
    ) -> CertificateTemplate:
        """Register a named background/layout pair for issuance."""
        self._require_manager(org_id, actor, "template.create")
        if not name.strip():
            raise InvalidRegistrationStateError(
                "Template name is required."
            )
        self._valid_layout(layout_json)
        return self._templates.create(
            uuid7(), org_id, name.strip(), background_media_id,
            layout_json, utcnow(),
        )

    def update(
        self,
        org_id: UUID,
        template_id: UUID,
        actor: UUID,
        name: str | None = None,
        background_media_id: UUID | None = None,
        layout_json: str | None = None,
        is_active: bool | None = None,
    ) -> CertificateTemplate:
        """Patch a template inside the owning org."""
        self._require_manager(org_id, actor, "template.update")
        row = self._templates.get(template_id)
        if row is None or row.org_id != org_id:
            raise NotFoundError("Template not found.")
        if name is not None and not name.strip():
            raise InvalidRegistrationStateError(
                "Template name is required."
            )
        self._valid_layout(layout_json)
        updated = self._templates.update(
            template_id,
            name=name.strip() if name is not None else None,
            background_media_id=background_media_id,
            layout_json=layout_json,
            is_active=is_active,
        )
        assert updated is not None
        return updated
