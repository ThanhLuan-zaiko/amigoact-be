"""Chat write side: send (reply + attachments), edit, file upload.

Split from ChatService so the read/lifecycle class stays small; both
share room resolution and event fan-out through chat.rooms.
"""

from __future__ import annotations

from uuid import UUID

import json

from chat.attachments import ChatAttachments
from chat.dtos import AttachmentBrief, ChatMessageSnapshot, MentionBrief
from chat.helpers import (
    MAX_ATTACHMENTS,
    REPLY_PREVIEW_LEN,
    bucket_of,
    bucket_of_uuid,
    build_index_items,
    encode_attachments,
    encode_mentions,
    message_snapshot,
)
from chat.channel_interfaces import ChannelStore
from chat.mentions import resolve_mentions
from chat.interfaces import (
    ActivityLookup,
    ChatEvents,
    ChatStore,
)
from chat.rooms import emit, emit_inbox, open_room
from core.exceptions import (
    ChannelArchivedError,
    ChatContentRequiredError,
    ForbiddenError,
    NotFoundError,
)
from core.ids import uuid7
from core.security import utcnow
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from rbac.interfaces import AccessControl


class ChatComposer:
    """Message mutations: send, reply, edit, and attachment upload."""

    def __init__(
        self,
        chat: ChatStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        access: AccessControl,
        events: ChatEvents,
        media: MediaRepository,
        attachments: ChatAttachments,
        activities: ActivityLookup | None = None,
        cipher=None,  # noqa: ANN001
        notifications=None,  # noqa: ANN001
        channels: ChannelStore | None = None,
    ) -> None:
        self._chat = chat
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events
        self._media = media
        self._attachments = attachments
        self._activities = activities
        self._cipher = cipher
        self._notifications = notifications
        self._channels = channels

    def _encrypt(self, text: str) -> str:
        return self._cipher.encrypt(text) if self._cipher else text

    def _snapshot(self, row) -> ChatMessageSnapshot:  # noqa: ANN001
        return message_snapshot(
            self._users, row, cipher=self._cipher, media=self._media
        )

    def _mentions(self, ctx, actor_id: UUID, text: str) -> list[MentionBrief]:  # noqa: ANN001
        """@name matches room-visible members (see mentions.py)."""
        return resolve_mentions(
            self._members, self._users, self._access, self._channels,
            ctx, actor_id, text,
        )

    def _notify_mentions(
        self, ctx, actor_id: UUID, room_id: UUID,  # noqa: ANN001
        message_id: UUID, text: str, mentions: list[MentionBrief],
    ) -> None:
        if self._notifications is None or not mentions:
            return
        brief = self._users.get_brief(actor_id)
        actor_name = brief.full_name if brief else "Someone"
        data = json.dumps(
            {"room_id": str(room_id), "message_id": str(message_id)}
        )
        for mention in mentions:
            try:
                self._notifications.notify(
                    mention.user_id,
                    "chat.mention",
                    f"{actor_name} nh\u1eafc \u0111\u1ebfn b\u1ea1n",
                    f"Trong {ctx.org.name}: {text[:80]}",
                    data,
                )
            except Exception:  # noqa: BLE001 - notifications are best-effort
                pass

    def _room(self, room_id: UUID, actor_id: UUID, action: str):
        return open_room(
            self._chat, self._orgs, self._members, self._access,
            self._activities, room_id, actor_id, action,
            channels=self._channels,
        )

    def _check_post(self, ctx, actor_id: UUID) -> None:  # noqa: ANN001
        """Channel gates: archived rooms freeze; managers-only rooms
        reject posts from regular members."""
        channel = ctx.channel
        if channel is None:
            return
        if channel.archived_at is not None:
            raise ChannelArchivedError("This channel is archived.")
        if (
            channel.post_policy == "managers"
            and ctx.org.owner_id != actor_id
            and not self._access.has_permission(
                ctx.org.id, actor_id, "chat:manage"
            )
        ):
            raise ForbiddenError("Only managers can post in this channel.")

    def send_message(
        self,
        room_id: UUID,
        actor_id: UUID,
        body: str,
        *,
        reply_to_id: UUID | None = None,
        attachment_ids: tuple[UUID, ...] | list[UUID] = (),
    ) -> ChatMessageSnapshot:
        ctx = self._room(room_id, actor_id, "chat.send")
        self._check_post(ctx, actor_id)
        text = (body or "").strip()
        attachment_ids = list(attachment_ids or ())[: MAX_ATTACHMENTS + 1]
        if len(attachment_ids) > MAX_ATTACHMENTS:
            raise ChatContentRequiredError(
                f"A message carries at most {MAX_ATTACHMENTS} attachments."
            )
        if not text and not attachment_ids:
            raise ChatContentRequiredError(
                "A message needs text or an attachment."
            )
        reply = self._reply_fields(room_id, reply_to_id)
        mentions = self._mentions(ctx, actor_id, text)

        now = utcnow()
        message_id = uuid7()
        attachments = self._attachments.resolve(
            room_id, actor_id, attachment_ids, message_id
        )
        try:
            row = self._chat.create(
                room_id,
                bucket_of(now),
                message_id,
                actor_id,
                self._encrypt(text),
                now,
                reply_to_id=reply_to_id if reply else None,
                reply_to_author=reply[0] if reply else None,
                reply_to_body=(
                    self._encrypt(reply[1]) if reply else None
                ),
                attachments_json=(
                    encode_attachments(attachments) if attachments else None
                ),
                mentions_json=(
                    encode_mentions(mentions) if mentions else None
                ),
            )
            # Media-tab index: attachments + links land in org_room_media
            # (links stay ciphertext, matching the body's at-rest rule).
            index_items = build_index_items(attachments, text, self._cipher)
            if index_items:
                self._chat.index_media(
                    room_id, bucket_of(now), message_id, actor_id, now,
                    index_items,
                )
        except Exception:
            self._attachments.release_claims(attachments)
            raise
        self._access.record(
            ctx.org.id, actor_id, "chat.send", "chat", message_id, "allowed"
        )
        # Own messages never inflate the sender's unread badge.
        self._chat.mark_read(room_id, actor_id, message_id, now)
        emit(self._events, room_id, "message.created", message_id, actor_id)
        emit_inbox(
            self._events,
            "message.created",
            room_id,
            ctx.org.id,
            (actor_id, ctx.dm.peer_id) if ctx.dm is not None else (),
        )
        self._notify_mentions(ctx, actor_id, room_id, message_id, text, mentions)
        return self._snapshot(row)

    def edit_message(
        self, room_id: UUID, actor_id: UUID, message_id: UUID, body: str
    ) -> ChatMessageSnapshot:
        """Only the author rewrites their own text."""
        ctx = self._room(room_id, actor_id, "chat.edit")
        channel = ctx.channel
        if channel is not None and channel.archived_at is not None:
            raise ChannelArchivedError("This channel is archived.")
        text = (body or "").strip()
        if not text:
            raise ChatContentRequiredError("A message cannot be empty.")
        row = self._chat.get(room_id, bucket_of_uuid(message_id), message_id)
        if row is None:
            raise NotFoundError("Message not found.")
        if row.author_id != actor_id:
            self._access.record(
                ctx.org.id, actor_id, "chat.edit", "chat",
                message_id, "denied",
            )
            raise ForbiddenError("Only the author can edit this message.")
        mentions = self._mentions(ctx, actor_id, text)
        now = utcnow()
        self._chat.update(
            row,
            self._encrypt(text),
            now,
            mentions_json=encode_mentions(mentions) if mentions else "",
        )
        self._access.record(
            ctx.org.id, actor_id, "chat.edit", "chat",
            message_id, "allowed",
        )
        # Edits never touch attachments, but the link set may change.
        self._chat.delete_media_index(
            room_id, row.bucket, message_id, kinds=("link",)
        )
        link_items = build_index_items([], text, self._cipher)
        if link_items:
            self._chat.index_media(
                room_id, row.bucket, message_id, row.author_id,
                row.created_at, link_items,
            )
        row.body = self._encrypt(text)
        row.edited_at = now
        row.mentions_json = encode_mentions(mentions) if mentions else ""
        emit(self._events, room_id, "message.edited", message_id, actor_id)
        emit_inbox(
            self._events,
            "message.edited",
            room_id,
            ctx.org.id,
            (actor_id, ctx.dm.peer_id) if ctx.dm is not None else (),
        )
        return self._snapshot(row)

    def create_attachment(
        self,
        room_id: UUID,
        actor_id: UUID,
        filename: str,
        mime: str,
        content: bytes,
    ) -> AttachmentBrief:
        """Validate room access, then stage the file as a chat attachment."""
        ctx = self._room(room_id, actor_id, "chat.attach")
        self._check_post(ctx, actor_id)
        brief = self._attachments.stage(
            ctx.org.id, room_id, actor_id, filename, mime, content
        )
        # resource stays None: audit readers are org managers who must
        # never learn a dm attachment's media id (the file path derives
        # straight from it).
        self._access.record(
            ctx.org.id, actor_id, "chat.attach", "chat",
            None, "allowed",
        )
        return brief

    def _reply_fields(
        self, room_id: UUID, reply_to_id: UUID | None
    ) -> tuple[str, str] | None:
        """Denormalize (author_name, snippet) so reads never join buckets."""
        if reply_to_id is None:
            return None
        target = self._chat.get(
            room_id, bucket_of_uuid(reply_to_id), reply_to_id
        )
        if target is None:
            raise NotFoundError("The replied-to message no longer exists.")
        brief = self._users.get_brief(target.author_id)
        author = brief.full_name if brief else "Unknown user"
        raw = target.body or ""
        if self._cipher is not None:
            raw = self._cipher.decrypt(raw)
        return author, raw[:REPLY_PREVIEW_LEN]
