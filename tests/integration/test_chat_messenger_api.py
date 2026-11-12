"""The messenger through HTTP: inbox, contacts, and messages with pictures and videos."""

from typing import Any

from tests.activity_helpers import Bearer, user
from tests.chat_helpers import channel, messages, send, sent
from tests.conftest import ApiContext
from tests.media_helpers import upload_video, uploaded
from tests.post_helpers import join, open_org


def _org_id(api: ApiContext, headers: dict[str, str], slug: str) -> str:
    value: str = api.client.get(f"/organizations/{slug}", headers=headers).json()["id"]
    return value


def _inbox(api: ApiContext, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = api.client.get("/chat/inbox", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_inbox_lists_rooms_of_every_organization_with_last_message_and_unread(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "lead")
    member, member_id = user(api, bearer, "mate")
    first = open_org(api, owner)
    second = open_org(api, owner)
    join(api, first, member)
    join(api, second, member)
    first_id = _org_id(api, owner, first)
    second_id = _org_id(api, owner, second)
    room = channel(api, owner, first, "Ban hau can")

    sent(api, owner, first_id, "Chao ca nha")
    sent(api, owner, room["id"], "Hop luc 8h\nnhe")

    items = _inbox(api, member)
    by_room = {item["room_id"]: item for item in items}
    assert {first_id, second_id, room["id"]} <= set(by_room)
    # Newest activity on top: the channel message came last.
    assert items[0]["room_id"] == room["id"]
    assert items[0]["kind"] == "channel"
    assert items[0]["org"]["slug"] == first
    assert items[0]["last_message"]["preview"] == "Hop luc 8h nhe"
    assert items[0]["last_message"]["author_id"] == owner_id
    assert items[0]["unread"] == 1
    assert by_room[first_id]["unread"] == 1
    assert by_room[second_id]["last_message"] is None
    assert by_room[second_id]["unread"] == 0
    assert by_room[first_id]["can_manage"] is False

    # Reading the room clears its count, and own messages never count.
    last = by_room[first_id]["last_message"]["id"]
    read = api.client.post(
        f"/rooms/{first_id}/read", headers=member, json={"message_id": last}
    )
    assert read.status_code == 204
    sent(api, member, first_id, "Da doc")
    after = {item["room_id"]: item for item in _inbox(api, member)}
    assert after[first_id]["unread"] == 0
    assert after[first_id]["last_message"]["author_id"] == member_id


def test_contacts_list_members_with_their_existing_direct_message(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "boss")
    member, member_id = user(api, bearer, "peer")
    slug = open_org(api, owner)
    join(api, slug, member)

    before = api.client.get("/chat/contacts", headers=member).json()["items"]
    assert [(item["user_id"], item["room_id"]) for item in before] == [(owner_id, None)]
    assert before[0]["org"]["slug"] == slug

    dm = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=member, json={"user_id": owner_id}
    ).json()
    after = api.client.get("/chat/contacts", headers=owner).json()["items"]
    assert [(item["user_id"], item["room_id"]) for item in after] == [
        (member_id, dm["room_id"])
    ]
    inbox = {item["room_id"]: item for item in _inbox(api, owner)}
    assert inbox[dm["room_id"]]["kind"] == "dm"
    assert inbox[dm["room_id"]]["peer_id"] == member_id


def test_message_carries_pictures_and_videos_that_room_members_can_open(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "shooter")
    member, _ = user(api, bearer, "viewer")
    outsider, _ = user(api, bearer, "stranger")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = _org_id(api, owner, slug)
    picture = uploaded(api, owner)["id"]
    video = upload_video(api, owner)

    message = sent(api, owner, org_id, "", attachment_ids=[video, picture])
    assert message["body"] == ""
    assert [item["id"] for item in message["attachments"]] == [video, picture]
    assert [item["kind"] for item in message["attachments"]] == ["video", "image"]
    assert message["attachments"][1]["url"] == f"/media/{picture}/file"

    listed = messages(api, member, org_id)[0]
    assert [item["id"] for item in listed["attachments"]] == [video, picture]
    opened = api.client.get(f"/media/{picture}/file", headers=member)
    assert opened.status_code == 200
    assert opened.headers["cache-control"] == "private, max-age=3600"
    assert api.client.get(f"/media/{picture}/file", headers=outsider).status_code == 404
    assert api.client.get(f"/media/{picture}/file").status_code == 404

    inbox = {item["room_id"]: item for item in _inbox(api, member)}
    last = inbox[org_id]["last_message"]
    assert (last["attachment_kind"], last["attachment_count"]) == ("mixed", 2)


def test_caption_can_be_cleared_only_on_a_message_with_files(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "author")
    slug = open_org(api, owner)
    org_id = _org_id(api, owner, slug)
    picture = uploaded(api, owner)["id"]
    album = sent(api, owner, org_id, "Anh dep", attachment_ids=[picture])
    text = sent(api, owner, org_id, "Chi chu")

    cleared = api.client.patch(
        f"/messages/{album['id']}", headers=owner, json={"body": ""}
    )
    assert cleared.status_code == 200
    assert cleared.json()["body"] == ""
    refused = api.client.patch(
        f"/messages/{text['id']}", headers=owner, json={"body": " "}
    )
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["type"] == "string_too_short"


def test_deleting_the_message_closes_the_file_to_the_room(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "sender")
    member, _ = user(api, bearer, "reader")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = _org_id(api, owner, slug)
    picture = uploaded(api, owner)["id"]
    message = sent(api, owner, org_id, "", attachment_ids=[picture])
    assert api.client.get(f"/media/{picture}/file", headers=member).status_code == 200

    deleted = api.client.delete(f"/messages/{message['id']}", headers=owner)
    assert deleted.status_code == 204
    assert api.client.get(f"/media/{picture}/file", headers=member).status_code == 404
    # The uploader still has the private file until the cleanup removes it.
    assert api.client.get(f"/media/{picture}/file", headers=owner).status_code == 200


def test_file_cannot_be_sent_twice_or_by_someone_else(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "first")
    member, _ = user(api, bearer, "second")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = _org_id(api, owner, slug)
    picture = uploaded(api, owner)["id"]
    sent(api, owner, org_id, "", attachment_ids=[picture])

    again = send(api, owner, org_id, "", attachment_ids=[picture])
    assert again.status_code == 422
    assert again.json()["detail"][0]["type"] == "attachment_in_use"
    stolen = send(api, member, org_id, "", attachment_ids=[picture])
    assert stolen.status_code == 404
    assert stolen.json()["detail"] == "media_not_found"
    assert len(messages(api, owner, org_id)) == 1
