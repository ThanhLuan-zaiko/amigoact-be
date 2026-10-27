"""Pure input rules for custom roles (no persistence, no actors)."""

from __future__ import annotations

from core.exceptions import InvalidRoleError
from rbac.catalog import ASSIGNABLE_PERMISSIONS, ROLE_COLORS

DESCRIPTION_MAX = 200


def valid_color(color: str | None) -> str | None:
    """None passes through (field omitted); "" means the default colour."""
    if color is None:
        return None
    if color != "" and color not in ROLE_COLORS:
        raise InvalidRoleError("Role colour is invalid.")
    return color


def valid_description(description: str | None) -> str:
    clean = (description or "").strip()
    if len(clean) > DESCRIPTION_MAX:
        raise InvalidRoleError("Role description is invalid.")
    return clean


def valid_permissions(permissions: list[str] | None) -> set[str]:
    codes = set(permissions or [])
    if not codes or not codes <= ASSIGNABLE_PERMISSIONS:
        raise InvalidRoleError("Role permissions are invalid.")
    return codes
