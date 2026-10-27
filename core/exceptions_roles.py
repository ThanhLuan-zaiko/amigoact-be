"""Role-hierarchy errors (split from exceptions.py to keep it under cap)."""

from __future__ import annotations

from core.exceptions import DomainError


class RoleHierarchyError(DomainError):
    """The target role ranks at or above the actor's own top role."""

    code = "ROLE_ABOVE_YOU"
    status = 403
