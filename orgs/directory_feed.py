"""Public-directory feed writes shared by org repository mutations."""

from __future__ import annotations

from orgs.model import Organization, OrganizationsPublic


def write_public_feed(org: Organization) -> None:
    """Mirror the org into the public directory feed under its kind."""
    OrganizationsPublic.create(
        kind=org.org_type or "organization",
        created_at=org.created_at,
        org_id=org.id,
        name=org.name,
        slug=org.slug,
    )


def delete_public_feed(org: Organization) -> None:
    """Pull the org out of the public directory (trash or hard delete)."""
    OrganizationsPublic.objects(
        kind=org.org_type or "organization",
        created_at=org.created_at,
        org_id=org.id,
    ).delete()
