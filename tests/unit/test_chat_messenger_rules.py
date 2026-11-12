"""Rules of the messenger that need no database: requests, previews, and inbox order."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.chat.attachments import IMAGE, VIDEO, kind_of
from src.chat.inbox import MIXED, attachment_kind, preview_text, sort_inbox
from src.chat.inbox_schemas import InboxOrg, InboxRoom, LastMessage
from src.chat.rules import ATTACHMENT_LIMIT, INBOX_PREVIEW
from src.chat.schemas import MessageEdit, MessageSend


def _error_types(error: ValidationError) -> set[str]:
    return {item["type"] for item in error.errors()}


def test_message_with_only_files_needs_no_text() -> None:
    files = [uuid.uuid7(), uuid.uuid7()]
    message = MessageSend(attachment_ids=files)
    assert message.body == ""
    assert message.attachment_ids == files


def test_message_without_text_or_files_is_refused_as_too_short() -> None:
    with pytest.raises(ValidationError) as caught:
        MessageSend(body="   ")
    assert "string_too_short" in _error_types(caught.value)
    with pytest.raises(ValidationError):
        MessageSend()


def test_files_are_bounded_unique_and_uuid7() -> None:
    with pytest.raises(ValidationError):
        MessageSend(attachment_ids=[uuid.uuid7() for _ in range(ATTACHMENT_LIMIT + 1)])
    same = uuid.uuid7()
    with pytest.raises(ValidationError) as caught:
        MessageSend(attachment_ids=[same, same])
    assert "attachment_duplicate" in _error_types(caught.value)
    with pytest.raises(ValidationError):
        MessageSend(attachment_ids=[uuid.uuid4()])


def test_edit_accepts_an_empty_caption_for_the_service_to_judge() -> None:
    assert MessageEdit(body="  ").body == ""


def test_kind_follows_the_detected_mime() -> None:
    assert kind_of("video/mp4") == VIDEO
    assert kind_of("image/png") == IMAGE
    assert kind_of(None) == IMAGE


def test_attachment_kind_names_one_kind_or_mixed() -> None:
    assert attachment_kind([]) is None
    assert attachment_kind([IMAGE, IMAGE]) == IMAGE
    assert attachment_kind([VIDEO]) == VIDEO
    assert attachment_kind([IMAGE, VIDEO]) == MIXED


def test_preview_is_one_short_line() -> None:
    assert preview_text("  Chao\n\nca   lop ") == "Chao ca lop"
    assert len(preview_text("x" * (INBOX_PREVIEW + 50))) == INBOX_PREVIEW


def _room(name: str, last_id: uuid.UUID | None) -> InboxRoom:
    org = InboxOrg(id=uuid.uuid7(), slug="clb", name="CLB", logo_url=None)
    last = (
        LastMessage(
            id=last_id,
            author_id=uuid.uuid7(),
            author_name="A",
            preview="hi",
            attachment_kind=None,
            attachment_count=0,
            created_at=datetime.now(UTC),
        )
        if last_id
        else None
    )
    return InboxRoom(
        room_id=uuid.uuid7(),
        kind="org",
        name=name,
        topic=None,
        restricted=False,
        org=org,
        avatar_url=None,
        peer_id=None,
        can_manage=False,
        unread=0,
        last_message=last,
    )


def test_inbox_puts_newest_activity_first_and_quiet_rooms_by_name() -> None:
    older, newer = uuid.uuid7(), uuid.uuid7()
    items = [
        _room("beta", None),
        _room("old", older),
        _room("Alpha", None),
        _room("new", newer),
    ]
    assert [room.name for room in sort_inbox(items)] == ["new", "old", "Alpha", "beta"]
