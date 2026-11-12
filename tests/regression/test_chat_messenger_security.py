"""Behavior the messenger must keep: text messages as before, and files only for the room."""

from tests.activity_helpers import Bearer, user
from tests.chat_helpers import channel, messages, send, sent
from tests.conftest import ApiContext
from tests.media_helpers import uploaded
from tests.post_helpers import join, open_org


def _org_id(api: ApiContext, headers: dict[str, str], slug: str) -> str:
    value: str = api.client.get(f"/organizations/{slug}", headers=headers).json()["id"]
    return value


def test_text_message_shape_is_unchanged_apart_from_an_empty_file_list(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "plain")
    slug = open_org(api, owner)
    org_id = _org_id(api, owner, slug)
    message = sent(api, owner, org_id, "  Chao  ")
    assert message["body"] == "Chao"
    assert message["attachments"] == []
    empty = send(api, owner, org_id, "   ")
    assert empty.status_code == 422
    assert empty.json()["detail"][0]["type"] == "string_too_short"


def test_unsent_upload_stays_private_to_its_uploader(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "keeper")
    member, _ = user(api, bearer, "nosy")
    slug = open_org(api, owner)
    join(api, slug, member)
    picture = uploaded(api, owner)["id"]
    assert api.client.get(f"/media/{picture}/file", headers=member).status_code == 404


def test_restricted_channel_files_stay_inside_the_channel(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "admin")
    insider, insider_id = user(api, bearer, "inner")
    member, _ = user(api, bearer, "outer")
    slug = open_org(api, owner)
    join(api, slug, insider)
    join(api, slug, member)
    room = channel(
        api, owner, slug, "Bi mat", visibility="restricted", member_ids=[insider_id]
    )
    picture = uploaded(api, owner)["id"]
    sent(api, owner, room["id"], "", attachment_ids=[picture])

    assert api.client.get(f"/media/{picture}/file", headers=insider).status_code == 200
    assert api.client.get(f"/media/{picture}/file", headers=member).status_code == 404
    inbox = api.client.get("/chat/inbox", headers=member).json()["items"]
    assert room["id"] not in [item["room_id"] for item in inbox]


def test_member_who_left_loses_the_rooms_and_their_files(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "stay")
    member, _ = user(api, bearer, "gone")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = _org_id(api, owner, slug)
    picture = uploaded(api, owner)["id"]
    sent(api, owner, org_id, "", attachment_ids=[picture])

    left = api.client.delete(f"/organizations/{slug}/membership", headers=member)
    assert left.status_code in (200, 204), left.text
    assert api.client.get(f"/media/{picture}/file", headers=member).status_code == 404
    assert api.client.get("/chat/inbox", headers=member).json()["items"] == []
    assert api.client.get("/chat/contacts", headers=member).json()["items"] == []


def test_failed_send_leaves_no_message_or_claim(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "retry")
    slug = open_org(api, owner)
    org_id = _org_id(api, owner, slug)
    picture = uploaded(api, owner)["id"]
    missing = "01890a5d-ac96-774b-bcce-b302099a8057"

    failed = send(api, owner, org_id, "", attachment_ids=[picture, missing])
    assert failed.status_code == 404
    assert messages(api, owner, org_id) == []
    # The first file was not claimed by the failed attempt, so it can still be sent.
    sent(api, owner, org_id, "", attachment_ids=[picture])
