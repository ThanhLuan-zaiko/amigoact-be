"""Limits and fixed values of the chat."""

from datetime import timedelta

MESSAGE_LIMIT = 2000
CHANNEL_NAME_MAX = 40
CHANNEL_TOPIC_MAX = 200
EMOJI_MAX = 16
SEND_LIMIT = 300
SEND_WINDOW = 60 * 60
TICKET_LIFETIME = timedelta(minutes=5)
SOCKET_LIFETIME_SECONDS = 30 * 60
OPEN = "open"
RESTRICTED = "restricted"
ROOM_ORG = "org"
ROOM_CHANNEL = "channel"
ROOM_DM = "dm"
REPLY_PREVIEW = 200
# A message carries at most this many pictures and videos, like an album.
ATTACHMENT_LIMIT = 10
INBOX_PREVIEW = 120
CONTACT_LIMIT = 1000
