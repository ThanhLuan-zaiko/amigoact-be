"""The permissions a role can hold. This list is the source of truth.

A code is "module.action", so a role can create without deleting. schema.sql seeds
the same codes into the permissions table, and a unit test keeps the two in step.
The owner holds every permission without any role.
"""

from typing import Final

ADMINISTRATOR: Final = "administrator"

ORGANIZATION_UPDATE: Final = "organization.update"

ROLES_CREATE: Final = "roles.create"
ROLES_UPDATE: Final = "roles.update"
ROLES_DELETE: Final = "roles.delete"
ROLES_ASSIGN: Final = "roles.assign"

MEMBERS_REMOVE: Final = "members.remove"
APPLICATIONS_REVIEW: Final = "applications.review"

ACTIVITIES_CREATE: Final = "activities.create"
ACTIVITIES_UPDATE: Final = "activities.update"
ACTIVITIES_DELETE: Final = "activities.delete"
ACTIVITIES_REGISTRATIONS: Final = "activities.registrations"

ATTENDANCE_CHECKIN: Final = "attendance.checkin"
ATTENDANCE_HOURS: Final = "attendance.hours"
ATTENDANCE_APPEALS: Final = "attendance.appeals"

CERTIFICATES_TEMPLATES: Final = "certificates.templates"
CERTIFICATES_ISSUE: Final = "certificates.issue"

POSTS_ANNOUNCE: Final = "posts.announce"
POSTS_PIN: Final = "posts.pin"
POSTS_MODERATE: Final = "posts.moderate"

CHANNELS_CREATE: Final = "channels.create"
CHANNELS_MANAGE: Final = "channels.manage"
CHANNELS_READ_RESTRICTED: Final = "channels.read_restricted"

# code -> module, in the order the interface lists them.
CATALOG: Final[dict[str, str]] = {
    ADMINISTRATOR: "organization",
    ORGANIZATION_UPDATE: "organization",
    ROLES_CREATE: "roles",
    ROLES_UPDATE: "roles",
    ROLES_DELETE: "roles",
    ROLES_ASSIGN: "roles",
    MEMBERS_REMOVE: "members",
    APPLICATIONS_REVIEW: "members",
    ACTIVITIES_CREATE: "activities",
    ACTIVITIES_UPDATE: "activities",
    ACTIVITIES_DELETE: "activities",
    ACTIVITIES_REGISTRATIONS: "activities",
    ATTENDANCE_CHECKIN: "attendance",
    ATTENDANCE_HOURS: "attendance",
    ATTENDANCE_APPEALS: "attendance",
    CERTIFICATES_TEMPLATES: "certificates",
    CERTIFICATES_ISSUE: "certificates",
    POSTS_ANNOUNCE: "posts",
    POSTS_PIN: "posts",
    POSTS_MODERATE: "posts",
    CHANNELS_CREATE: "chat",
    CHANNELS_MANAGE: "chat",
    CHANNELS_READ_RESTRICTED: "chat",
}
ALL: Final = frozenset(CATALOG)
# What the Admin role of a new organization holds. Handing out roles stays with the owner
# until the owner chooses to share it.
DEFAULT_ADMIN: Final = ALL - {
    ADMINISTRATOR,
    ROLES_CREATE,
    ROLES_UPDATE,
    ROLES_DELETE,
    ROLES_ASSIGN,
}
