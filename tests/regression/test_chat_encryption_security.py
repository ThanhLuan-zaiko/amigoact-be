import uuid

import pytest
from sqlalchemy import select, update

from src.app import app
from src.chat.crypto import CipherError
from src.models.chat import OrgRoomMessage
from tests.activity_helpers import Bearer, user
from tests.chat_helpers import messages, sent
from tests.conftest import ApiContext
from tests.post_helpers import open_org


def _set_body(message_id: str, body: str) -> None:
    with app.state.engine.begin() as connection:
        connection.execute(
            update(OrgRoomMessage)
            .where(OrgRoomMessage.message_id == uuid.UUID(message_id))
            .values(body=body)
        )


def _general_room(api: ApiContext, headers: dict[str, str], slug: str) -> str:
    room_id: str = api.client.get(f"/organizations/{slug}", headers=headers).json()[
        "id"
    ]
    return room_id


def test_ciphertext_copied_to_another_row_is_refused(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "copier")
    slug = open_org(api, owner)
    room = _general_room(api, owner, slug)
    first = sent(api, owner, room, "Tin thu nhat")
    second = sent(api, owner, room, "Tin thu hai")
    _set_body(second["id"], _sealed_body(first["id"]))

    with pytest.raises(CipherError):
        messages(api, owner, room)


def test_plain_text_in_the_database_is_refused_not_shown(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "plainer")
    slug = open_org(api, owner)
    room = _general_room(api, owner, slug)
    message = sent(api, owner, room, "Ban dau")
    _set_body(message["id"], "viet thang khong ma hoa")

    with pytest.raises(CipherError):
        messages(api, owner, room)


def _sealed_body(message_id: str) -> str:
    with app.state.engine.connect() as connection:
        body: str = connection.scalar(
            select(OrgRoomMessage.body).where(
                OrgRoomMessage.message_id == uuid.UUID(message_id)
            )
        )
    return body
