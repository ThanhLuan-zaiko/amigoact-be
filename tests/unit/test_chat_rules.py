import uuid

import pytest
from pydantic import ValidationError

from src.chat.rooms import Room, can_delete
from src.chat.rules import (
    EMOJI_MAX,
    MESSAGE_LIMIT,
    REPLY_PREVIEW,
    ROOM_CHANNEL,
    ROOM_DM,
    ROOM_ORG,
)
from src.chat.schemas import ChannelCreate, DmOpen, MessageSend, ReactionAdd


def test_message_body_is_trimmed_and_bounded() -> None:
    assert MessageSend(body="  Chao  ").body == "Chao"
    with pytest.raises(ValidationError):
        MessageSend(body="   ")
    with pytest.raises(ValidationError):
        MessageSend(body="x" * (MESSAGE_LIMIT + 1))


def test_reply_must_name_a_message_id_in_uuid7() -> None:
    with pytest.raises(ValidationError):
        MessageSend(body="a", reply_to_id=uuid.uuid4())


def test_channel_name_and_visibility_are_checked() -> None:
    with pytest.raises(ValidationError):
        ChannelCreate(name="a\nb")
    with pytest.raises(ValidationError):
        ChannelCreate(name="x" * 41)
    with pytest.raises(ValidationError):
        ChannelCreate(name="Chung", visibility="secret")
    assert ChannelCreate(name="  Chung  ").visibility == "open"


def test_reaction_emoji_has_a_length_limit() -> None:
    assert ReactionAdd(emoji="+1").emoji == "+1"
    with pytest.raises(ValidationError):
        ReactionAdd(emoji="")
    with pytest.raises(ValidationError):
        ReactionAdd(emoji="x" * (EMOJI_MAX + 1))


def test_direct_message_needs_a_uuid7_peer() -> None:
    with pytest.raises(ValidationError):
        DmOpen(user_id=uuid.uuid4())


def test_reply_preview_keeps_a_short_quote() -> None:
    assert REPLY_PREVIEW == 200


def _room(kind: str, is_manager: bool) -> Room:
    return Room(uuid.uuid7(), uuid.uuid7(), kind, None, is_manager)


def test_author_deletes_own_message_in_every_room() -> None:
    author = uuid.uuid7()
    for kind in (ROOM_ORG, ROOM_CHANNEL, ROOM_DM):
        assert can_delete(_room(kind, False), author, author)


def test_managers_delete_others_in_org_rooms_and_channels_only() -> None:
    author, manager = uuid.uuid7(), uuid.uuid7()
    assert can_delete(_room(ROOM_ORG, True), author, manager)
    assert can_delete(_room(ROOM_CHANNEL, True), author, manager)
    assert not can_delete(_room(ROOM_ORG, False), author, manager)
    assert not can_delete(_room(ROOM_CHANNEL, False), author, manager)


def test_nobody_but_the_author_deletes_in_a_direct_message() -> None:
    author, peer = uuid.uuid7(), uuid.uuid7()
    # Even a room flagged as managed gives no delete right in a DM.
    assert not can_delete(_room(ROOM_DM, True), author, peer)
    assert not can_delete(_room(ROOM_DM, False), author, peer)
