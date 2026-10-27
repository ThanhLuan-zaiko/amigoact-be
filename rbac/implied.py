"""Permission checks that honour umbrella codes (see IMPLIED_PERMISSIONS)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from rbac.catalog import IMPLIED_PERMISSIONS

if TYPE_CHECKING:
    from rbac.interfaces import AccessControl


def holds(
    access: "AccessControl", org_id: UUID, user_id: UUID, code: str
) -> bool:
    """True when the user holds `code` or an umbrella code that implies it."""
    if access.has_permission(org_id, user_id, code):
        return True
    return any(
        code in implied and access.has_permission(org_id, user_id, parent)
        for parent, implied in IMPLIED_PERMISSIONS.items()
    )
