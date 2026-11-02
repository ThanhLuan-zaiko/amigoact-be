import uuid

from src.chat.crypto import PREFIX
from src.models.chat import OrgRoomMessage
from tests.activity_helpers import Bearer, user
from tests.chat_helpers import messages, sent
from tests.conftest import ApiContext
from tests.media_helpers import db_row
from tests.post_helpers import open_org


def _general_room(api: ApiContext, headers: dict[str, str], slug: str) -> str:
    room_id: str = api.client.get(f"/organizations/{slug}", headers=headers).json()[
        "id"
    ]
    return room_id


def test_message_text_is_stored_sealed_and_read_back_in_clear(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "sealer")
    slug = open_org(api, owner)
    room = _general_room(api, owner, slug)

    message = sent(api, owner, room, "Noi dung bi mat")

    row = db_row(OrgRoomMessage, uuid.UUID(message["id"]))
    assert row.body.startswith(PREFIX)
    assert "Noi dung bi mat" not in row.body
    assert messages(api, owner, room)[0]["body"] == "Noi dung bi mat"


def test_reply_preview_is_sealed_as_well(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "quoted")
    slug = open_org(api, owner)
    room = _general_room(api, owner, slug)
    parent = sent(api, owner, room, "Tin goc can trich dan")
    reply = sent(api, owner, room, "Tra loi", reply_to_id=parent["id"])

    row = db_row(OrgRoomMessage, uuid.UUID(reply["id"]))

    assert row.reply_to_body is not None
    assert row.reply_to_body.startswith(PREFIX)
    assert "Tin goc can trich dan" not in row.reply_to_body
    assert messages(api, owner, room)[0]["reply_to"]["body"] == "Tin goc can trich dan"


def test_edit_seals_the_new_text(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "reseal")
    slug = open_org(api, owner)
    room = _general_room(api, owner, slug)
    message = sent(api, owner, room, "Ban dau")

    api.client.patch(
        f"/messages/{message['id']}", headers=owner, json={"body": "Ban moi"}
    )

    row = db_row(OrgRoomMessage, uuid.UUID(message["id"]))
    assert row.body.startswith(PREFIX)
    assert "Ban moi" not in row.body
    assert messages(api, owner, room)[0]["body"] == "Ban moi"
