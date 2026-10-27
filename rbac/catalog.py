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
    "activity:delete": "Trash, restore and permanently delete activities.",
    "post:create": "Write drafts and discussions and manage own posts.",
    "post:publish": "Publish posts onto the org board.",
    "post:edit-any": "Edit posts written by other members.",
    "post:delete-any": "Trash, restore and delete posts of other members.",
    "post:announce": "Publish announcements on the org board.",
    "post:manage": "Pin, edit or remove any org post or comment.",
    "comment:create": "Comment on org board posts.",
    "comment:delete-any": "Remove comments written by other members.",
    "chat:manage": "Full chat control: implies the three chat:* codes below.",
    "chat:moderate": "Pin messages and remove chat messages of other members.",
    "chat:channel": "Create, edit and archive channels and manage their rosters.",
    "chat:view-private": "See and enter restricted channels without a roster seat.",
    "chat:mention-all": "Notify every room member with @all.",
    "chat:timeout": "Temporarily mute members in chat.",
    "chat:attach": "Attach files when the org restricts attachments.",
    "tag:manage": "Create, rename, merge and delete org activity tags.",
}

# Legacy umbrella codes: holding the key counts as holding every value, so
# roles that predate the chat split keep working unchanged.
IMPLIED_PERMISSIONS: dict[str, frozenset[str]] = {
    "chat:manage": frozenset(
        {
            "chat:moderate",
            "chat:channel",
            "chat:view-private",
            "chat:mention-all",
            "chat:timeout",
            "chat:attach",
        }
    ),
    "activity:manage": frozenset({"activity:delete"}),
    # Roles that predate the post split keep moderating unchanged.
    "post:manage": frozenset(
        {"post:edit-any", "post:delete-any", "comment:delete-any"}
    ),
}

# Permissions a custom org role may carry. media:upload stays out:
# every active member can already upload into the org gallery, so the
# code has no enforcement point to hang on today.
ASSIGNABLE_PERMISSIONS: frozenset[str] = frozenset(
    code for code in PERMISSIONS if code != "media:upload"
)

# Permissions the owner may hand to every active member as the baseline.
# Moderation, admin and ownership-adjacent codes stay role-only.
BASELINE_PERMISSIONS: frozenset[str] = frozenset(
    {
        "member:view",
        "member:invite",
        "activity:view",
        "activity:create",
        "post:create",
        "post:publish",
        "comment:create",
        "post:announce",
    }
)

# Role colour keys: neutral chrome plus the three semantic tones the
# frontend palette allows. "" means the default (zinc).
ROLE_COLORS: tuple[str, ...] = ("zinc", "red", "amber", "emerald")

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
            "post:create",
            "post:publish",
            "post:edit-any",
            "post:delete-any",
            "post:announce",
            "post:manage",
            "comment:create",
            "comment:delete-any",
            "chat:manage",
            "tag:manage",
        },
    },
}
