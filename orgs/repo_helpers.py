"""Small persistence helpers for CqlOrgRepository: contact flattening,
verification-queue mirroring, and id generation."""

from __future__ import annotations

from uuid import UUID

from core.ids import uuid7
from orgs.interfaces import OrgContactDetails
from orgs.model import Organization, OrganizationsByLegalStatus

CONTACT_FIELDS = (
    "email",
    "phone",
    "website",
    "address",
    "city",
    "country",
    "legal_name",
    "license_number",
    "is_personal",
)


def contact_fields(contact: OrgContactDetails | None) -> dict[str, object]:
    """Flatten the contact value object into model update kwargs."""
    if contact is None:
        return {}
    return {name: getattr(contact, name) for name in CONTACT_FIELDS}


def queue_write(org: Organization) -> None:
    """Mirror the org into the platform verification queue feed."""
    OrganizationsByLegalStatus.create(
        legal_status=org.legal_status or "none",
        created_at=org.created_at,
        org_id=org.id,
        name=org.name,
        slug=org.slug,
    )


def queue_delete(org: Organization) -> None:
    """Drop the org's verification-queue row (trash or hard delete)."""
    OrganizationsByLegalStatus.objects(
        legal_status=org.legal_status or "none",
        created_at=org.created_at,
        org_id=org.id,
    ).delete()


def generate_org_id() -> UUID:
    """Application-side UUIDv7 primary key for new orgs."""
    return uuid7()
