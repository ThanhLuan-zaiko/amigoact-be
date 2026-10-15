"""Update-path rules for OrgService: contact limits and legal identity diffs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.exceptions import InvalidBusinessProfileError
from orgs.interfaces import OrgContactDetails, OrgLegalEdit

if TYPE_CHECKING:
    from orgs.model import Organization

CONTACT_LIMITS = {
    "email": 254,
    "phone": 20,
    "website": 255,
    "address": 255,
    "city": 100,
    "country": 100,
    "legal_name": 255,
    "license_number": 100,
}

LEGAL_EDIT_FIELDS = (
    "tax_code",
    "legal_rep_name",
    "legal_rep_id",
    "legal_rep_position",
)


def clean_contact(contact: OrgContactDetails | None) -> OrgContactDetails | None:
    """Trim contact strings and enforce column length limits."""
    if contact is None:
        return None
    cleaned: dict[str, object] = {}
    for field_name, limit in CONTACT_LIMITS.items():
        value = getattr(contact, field_name)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None and len(value) > limit:
            raise InvalidBusinessProfileError(
                f"Org {field_name.replace('_', ' ')} is invalid."
            )
        cleaned[field_name] = value
    return OrgContactDetails(is_personal=contact.is_personal, **cleaned)


def field_diffs(
    org: Organization, fields: dict[str, object]
) -> dict[str, dict[str, object]]:
    """old->new map for keys whose stored value actually changed."""
    return {
        key: {"old": getattr(org, key, None), "new": new}
        for key, new in fields.items()
        if new != getattr(org, key, None)
    }


def legal_edit_fields(
    org: Organization, legal: OrgLegalEdit | None
) -> dict[str, object]:
    """Diff explicitly sent legal fields; business orgs keep the trio."""
    if legal is None or not legal.provided:
        return {}
    if org.org_type != "business":
        raise InvalidBusinessProfileError(
            "Legal identity applies to business organizations."
        )
    fields: dict[str, object] = {}
    for key in LEGAL_EDIT_FIELDS:
        if key not in legal.provided:
            continue
        new = getattr(legal, key)
        if key != "legal_rep_position" and not new:
            raise InvalidBusinessProfileError(
                "Business orgs require tax_code and legal representative."
            )
        if new != getattr(org, key, None):
            fields[key] = new
    return fields
