"""What each route that changes data sends live. tests/unit/test_realtime_coverage.py
fails when a POST, PUT, PATCH, or DELETE route is missing here, so a new route
has to say whether open pages learn about it.

Each value starts with one of:
- "emits:"   the events it sends and on which topics
- "none:"    why nobody else needs to know at once
- "pending:" the rollout step that will add it (see docs/realtime.md)
"""

ACCOUNT = "none: only the person's own pages show it, and they reload on save"
AUTH = "none: sign-in state lives in cookies; sockets end with their ticket"
TICKET = "none: issues a socket ticket"
PHASE_2 = "pending: phase 2 (activities, registrations, waitlist)"
PHASE_3 = "pending: phase 3 (posts, comments, attendance)"
PHASE_4 = "pending: phase 4 (organization profile, certificates, hours)"
MESSAGE = "emits: message.created/updated/deleted on room:<id>"
NOTIFY_READ = "emits: notification.read/read_all on user:<id>"
ROOMS = "emits: rooms.changed on org:<id>, or user:<id> for the people it adds"
JOIN = (
    "emits: applications.changed on org-managers:<id> or members.changed on"
    " org:<id>, membership.changed on user:<id>, notification.created"
)
DECIDE = (
    "emits: applications.changed on org-managers:<id>, members.changed on"
    " org:<id> when approved, membership.changed and notification.created on user:<id>"
)
LEAVE = (
    "emits: members.changed or applications.changed, membership.changed,"
    " notification.created/deleted; revokes the person's org and room topics"
)
ROLE = (
    "emits: members.changed on org:<id>, membership.changed on user:<id>;"
    " a demotion revokes org-managers:<id> and restricted rooms"
)

ROUTES: dict[tuple[str, str], str] = {
    ("PATCH", "/account/me"): ACCOUNT,
    ("PUT", "/account/me/avatar"): ACCOUNT,
    ("POST", "/auth/email/resend"): AUTH,
    ("POST", "/auth/email/verify"): AUTH,
    ("POST", "/auth/login"): AUTH,
    ("POST", "/auth/logout"): AUTH,
    ("POST", "/auth/logout-all"): AUTH,
    ("POST", "/auth/password/change"): AUTH,
    ("POST", "/auth/password/forgot"): AUTH,
    ("POST", "/auth/password/reset"): AUTH,
    ("POST", "/auth/refresh"): AUTH,
    ("POST", "/auth/register"): AUTH,
    ("DELETE", "/auth/sessions/{session_id}"): AUTH,
    ("POST", "/chat/tickets"): TICKET,
    ("POST", "/realtime/tickets"): TICKET,
    ("POST", "/media"): "none: an upload is private until something uses it",
    ("PUT", "/notifications/preferences"): "none: affects only future notifications",
    ("POST", "/notifications/read-all"): NOTIFY_READ,
    ("POST", "/notifications/{notification_id}/read"): NOTIFY_READ,
    # Chat
    ("POST", "/rooms/{room_id}/messages"): MESSAGE,
    ("PATCH", "/messages/{message_id}"): MESSAGE,
    ("DELETE", "/messages/{message_id}"): MESSAGE,
    ("POST", "/messages/{message_id}/reactions"): MESSAGE,
    ("DELETE", "/messages/{message_id}/reactions/{emoji}"): MESSAGE,
    ("POST", "/rooms/{room_id}/pins/{message_id}"): MESSAGE,
    ("DELETE", "/rooms/{room_id}/pins/{message_id}"): MESSAGE,
    ("POST", "/rooms/{room_id}/read"): "none: the reader's own position",
    ("POST", "/organizations/{slug}/chat/channels"): ROOMS,
    ("POST", "/chat/channels/{channel_id}/archive"): ROOMS,
    ("POST", "/chat/channels/{channel_id}/members"): ROOMS,
    ("DELETE", "/chat/channels/{channel_id}/members/{user_id}"): (
        "emits: revokes room:<id> for the removed person"
    ),
    ("POST", "/organizations/{slug}/chat/dms"): ROOMS,
    # Membership
    ("POST", "/organizations/{slug}/join"): JOIN,
    ("DELETE", "/organizations/{slug}/membership"): LEAVE,
    ("POST", "/organizations/{slug}/applications/{user_id}/approve"): DECIDE,
    ("POST", "/organizations/{slug}/applications/{user_id}/reject"): DECIDE,
    ("PATCH", "/organizations/{slug}/members/{user_id}"): ROLE,
    ("DELETE", "/organizations/{slug}/members/{user_id}"): LEAVE,
    ("POST", "/organizations"): "none: a new organization has nobody watching yet",
    # Later phases
    ("PATCH", "/organizations/{slug}"): PHASE_4,
    ("DELETE", "/organizations/{slug}"): PHASE_4,
    ("DELETE", "/organizations/mine/deleted/{org_id}"): PHASE_4,
    ("POST", "/organizations/mine/deleted/{org_id}/restore"): PHASE_4,
    ("PUT", "/organizations/{slug}/cover"): PHASE_4,
    ("PUT", "/organizations/{slug}/logo"): PHASE_4,
    ("PUT", "/organizations/{slug}/pictures"): PHASE_4,
    ("POST", "/organizations/{slug}/gallery"): PHASE_4,
    ("DELETE", "/organizations/{slug}/gallery/{asset_id}"): PHASE_4,
    ("PUT", "/organizations/{slug}/hour-rule"): PHASE_4,
    ("POST", "/organizations/{slug}/certificate-templates"): PHASE_4,
    ("PATCH", "/certificate-templates/{template_id}"): PHASE_4,
    ("POST", "/certificates/{certificate_id}/reinstate"): PHASE_4,
    ("POST", "/certificates/{certificate_id}/revoke"): PHASE_4,
    ("POST", "/activities/{activity_id}/certificates"): PHASE_4,
    ("POST", "/activities/{activity_id}/hour-adjustments"): PHASE_4,
    ("POST", "/organizations/{slug}/activities"): PHASE_2,
    ("PATCH", "/activities/{activity_id}"): PHASE_2,
    ("DELETE", "/activities/{activity_id}"): PHASE_2,
    ("POST", "/activities/{activity_id}/cancel"): PHASE_2,
    ("POST", "/activities/{activity_id}/complete"): PHASE_2,
    ("PUT", "/activities/{activity_id}/cover"): PHASE_2,
    ("POST", "/activities/{activity_id}/publish"): PHASE_2,
    ("DELETE", "/activities/{activity_id}/purge"): PHASE_2,
    ("POST", "/activities/{activity_id}/restore"): PHASE_2,
    ("POST", "/activities/{activity_id}/registrations"): PHASE_2,
    ("POST", "/activities/{activity_id}/shifts"): PHASE_2,
    ("PUT", "/activities/{activity_id}/shifts/{shift_id}"): PHASE_2,
    ("DELETE", "/activities/{activity_id}/shifts/{shift_id}"): PHASE_2,
    ("DELETE", "/registrations/{registration_id}"): PHASE_2,
    ("POST", "/registrations/{registration_id}/approve"): PHASE_2,
    ("POST", "/registrations/{registration_id}/reject"): PHASE_2,
    ("POST", "/activities/{activity_id}/attendance-sessions"): PHASE_3,
    ("POST", "/attendance-sessions/{session_id}/close"): PHASE_3,
    ("POST", "/attendance-sessions/{session_id}/records"): PHASE_3,
    ("POST", "/attendance/check-in"): PHASE_3,
    ("DELETE", "/attendance-records/{record_id}"): PHASE_3,
    ("POST", "/attendance-records/{record_id}/verify"): PHASE_3,
    ("POST", "/registrations/{registration_id}/appeals"): PHASE_3,
    ("POST", "/appeals/{appeal_id}/approve"): PHASE_3,
    ("POST", "/appeals/{appeal_id}/reject"): PHASE_3,
    ("POST", "/organizations/{slug}/posts"): PHASE_3,
    ("PATCH", "/posts/{post_id}"): PHASE_3,
    ("DELETE", "/posts/{post_id}"): PHASE_3,
    ("POST", "/posts/{post_id}/comments"): PHASE_3,
    ("POST", "/posts/{post_id}/hide"): PHASE_3,
    ("POST", "/posts/{post_id}/unhide"): PHASE_3,
    ("POST", "/posts/{post_id}/pin"): PHASE_3,
    ("POST", "/posts/{post_id}/unpin"): PHASE_3,
    ("POST", "/posts/{post_id}/publish"): PHASE_3,
    ("DELETE", "/posts/{post_id}/purge"): PHASE_3,
    ("POST", "/posts/{post_id}/restore"): PHASE_3,
    ("PATCH", "/comments/{comment_id}"): PHASE_3,
    ("DELETE", "/comments/{comment_id}"): PHASE_3,
    ("POST", "/comments/{comment_id}/restore"): PHASE_3,
}
