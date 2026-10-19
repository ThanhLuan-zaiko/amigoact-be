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
    "activity:view": "View draft and internal activity details.",
    "activity:create": "Create activities inside the org.",
    "activity:manage": "Publish, edit, staff, and cancel activities.",
    "post:announce": "Publish announcements on the org board.",
    "post:manage": "Pin, edit or remove any org post or comment.",
    "chat:manage": "Remove chat messages of other members.",
    "tag:manage": "Create, rename, merge and delete org activity tags.",
}

# Permissions a custom org role may carry. media:upload stays out:
# every active member can already upload into the org gallery, so the
# code has no enforcement point to hang on today.
ASSIGNABLE_PERMISSIONS: frozenset[str] = frozenset(
    code for code in PERMISSIONS if code != "media:upload"
)

# Display names that can never label a custom role: they collide with
# the built-in pseudo-roles (owner/member) or seeded system roles.
RESERVED_ROLE_NAMES: frozenset[str] = frozenset(
    {"owner", "admin", "member", "platform_admin"}
)

# Well-known ids let seeding and role lookup stay deterministic.
# (Fixed constants, not generated PKs: system roles are reference data,
# so the UUIDv7 rule for new entity ids does not apply here.)
ADMIN_ROLE_ID = UUID("0197f6a0-9c3b-7f2e-8d4a-b1c2d3e4f501")
# Platform-wide administrator; deliberately kept OUT of SYSTEM_ROLES so the
# org-scoped resolve_role() can never hand it to an org member.
PLATFORM_ADMIN_ROLE_ID = UUID("0197f6a0-9c3b-7f2e-8d4a-b1c2d3e4f502")

SYSTEM_ROLES: dict[str, dict[str, object]] = {
    "admin": {
        "id": ADMIN_ROLE_ID,
        "description": "Org administrator: member management rights.",
        "permissions": {
            "member:invite",
            "member:suspend",
            "member:remove",
            "member:view",
            "activity:view",
            "activity:create",
            "activity:manage",
            "post:announce",
            "post:manage",
            "chat:manage",
            "tag:manage",
        },
    },
}
