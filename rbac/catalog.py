"""Permission catalog and well-known system roles for RBAC seeding."""

from __future__ import annotations

from uuid import UUID

# Permission codes are a stable public contract. Modules mirror the
# `permissions.module` values in schemas.cql section 3.
PERMISSIONS: dict[str, str] = {
    "member:view": "View the org member roster.",
    "member:invite": "Invite people into the org.",
    "member:suspend": "Suspend or reactivate members.",
    "member:remove": "Remove members from the org.",
    "member:role-assign": "Assign or revoke member roles.",
    "org:update": "Update the org profile and join policy.",
    "media:upload": "Upload files into the org gallery.",
    "media:manage": "Manage org gallery files.",
}

# Well-known ids let seeding and role lookup stay deterministic.
# (Fixed constants, not generated PKs: system roles are reference data,
# so the UUIDv7 rule for new entity ids does not apply here.)
ADMIN_ROLE_ID = UUID("0197f6a0-9c3b-7f2e-8d4a-b1c2d3e4f501")

SYSTEM_ROLES: dict[str, dict[str, object]] = {
    "admin": {
        "id": ADMIN_ROLE_ID,
        "description": "Org administrator: member management rights.",
        "permissions": {
            "member:invite",
            "member:suspend",
            "member:remove",
            "member:view",
        },
    },
}
