from typing import Any

from tests.activity_helpers import Bearer, user
from tests.chat_helpers import channel, messages, send, sent, ticket
from tests.conftest import ApiContext
from tests.post_helpers import join, open_org


def test_general_room_carries_messages_between_members(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "host")
    member, _ = user(api, bearer, "guest")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]

    first = sent(api, owner, org_id, "Chao ca lop")
    reply = sent(api, member, org_id, "Chao ban", reply_to_id=first["id"])

    items = messages(api, member, org_id)
    assert [item["id"] for item in items] == [reply["id"], first["id"]]
    assert items[0]["reply_to"] == {
        "id": first["id"],
        "author_name": first["author_name"],
        "body": "Chao ca lop",
    }
    assert items[0]["author_name"] == "Test User"


def test_open_channel_is_visible_to_members_and_archive_stops_writing(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "boss")
    member, _ = user(api, bearer, "crew")
    slug = open_org(api, owner)
    join(api, slug, member)
    room = channel(api, owner, slug, "Tin chung", topic="Thong bao")

    listed = api.client.get(
        f"/organizations/{slug}/chat/channels", headers=member
    ).json()
    assert room["id"] in [item["id"] for item in listed["items"]]

    sent(api, member, room["id"], "Xin chao")
    archive = api.client.post(f"/chat/channels/{room['id']}/archive", headers=owner)
    assert archive.status_code == 204

    assert len(messages(api, member, room["id"])) == 1
    blocked = send(api, member, room["id"], "Van con khong")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "channel_archived"
    listed = api.client.get(
        f"/organizations/{slug}/chat/channels", headers=member
    ).json()
    assert room["id"] not in [item["id"] for item in listed["items"]]


def test_restricted_channel_opens_for_the_people_added(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "lead")
    inside, inside_id = user(api, bearer, "inside")
    outside, _ = user(api, bearer, "outside")
    slug = open_org(api, owner)
    join(api, slug, inside)
    join(api, slug, outside)
    room = channel(
        api,
        owner,
        slug,
        "Ban dieu hanh",
        visibility="restricted",
        member_ids=[inside_id],
    )

    before_joining = api.client.get(
        f"/organizations/{slug}/chat/channels", headers=outside
    ).json()
    assert room["id"] not in [item["id"] for item in before_joining["items"]]
    assert (
        api.client.get(f"/rooms/{room['id']}/messages", headers=outside).status_code
        == 404
    )

    sent(api, inside, room["id"], "Hop nhe")
    assert len(messages(api, owner, room["id"])) == 1


def test_direct_message_opens_once_and_both_sides_see_it(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "dm_owner")
    member, member_id = user(api, bearer, "dm_member")
    slug = open_org(api, owner)
    join(api, slug, member)
    owner_id = api.client.get("/account/me", headers=owner).json()["id"]

    opened = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=owner, json={"user_id": member_id}
    )
    again = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=member, json={"user_id": owner_id}
    )

    assert opened.status_code == 201, opened.text
    assert again.json()["room_id"] == opened.json()["room_id"]
    room_id = opened.json()["room_id"]
    sent(api, owner, room_id, "Rieng tu")
    listed = api.client.get(f"/organizations/{slug}/chat/dms", headers=member).json()
    assert [item["room_id"] for item in listed["items"]] == [room_id]
    assert messages(api, member, room_id)[0]["body"] == "Rieng tu"


def test_direct_message_author_deletes_and_either_side_pins(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "dm_del_owner")
    peer, peer_id = user(api, bearer, "dm_del_peer")
    slug = open_org(api, owner)
    join(api, slug, peer)
    room_id = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=owner, json={"user_id": peer_id}
    ).json()["room_id"]
    mine = sent(api, owner, room_id, "Cua toi")
    theirs = sent(api, peer, room_id, "Cua ban")

    pin = api.client.post(f"/rooms/{room_id}/pins/{theirs['id']}", headers=owner)
    deleted = api.client.delete(f"/messages/{mine['id']}", headers=owner)

    assert pin.status_code == 204
    assert deleted.status_code == 204
    left = messages(api, peer, room_id)
    assert [item["id"] for item in left] == [theirs["id"]]
    assert left[0]["pinned"] is True


def test_edit_delete_react_and_pin(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "mod_lead")
    member, _ = user(api, bearer, "mod_member")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]
    message = sent(api, member, org_id, "Sai chinh ta")

    edited = api.client.patch(
        f"/messages/{message['id']}", headers=member, json={"body": "Dung roi"}
    )
    assert edited.status_code == 200
    assert edited.json()["edited_at"] is not None

    api.client.post(
        f"/messages/{message['id']}/reactions", headers=owner, json={"emoji": "+1"}
    )
    api.client.post(
        f"/messages/{message['id']}/reactions", headers=owner, json={"emoji": "+1"}
    )
    reacted = messages(api, owner, org_id)[0]["reactions"]
    assert reacted == [{"emoji": "+1", "count": 1, "mine": True}]
    api.client.delete(f"/messages/{message['id']}/reactions/+1", headers=owner)
    assert messages(api, owner, org_id)[0]["reactions"] == []

    pin = api.client.post(f"/rooms/{org_id}/pins/{message['id']}", headers=owner)
    assert pin.status_code == 204
    pins = api.client.get(f"/rooms/{org_id}/pins", headers=member).json()["items"]
    assert [item["id"] for item in pins] == [message["id"]]
    assert pins[0]["pinned"] is True
    api.client.delete(f"/rooms/{org_id}/pins/{message['id']}", headers=owner)
    assert api.client.get(f"/rooms/{org_id}/pins", headers=member).json()["items"] == []

    deleted = api.client.delete(f"/messages/{message['id']}", headers=owner)
    assert deleted.status_code == 204
    assert messages(api, owner, org_id) == []


def test_unread_counts_follow_the_read_position(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "news")
    reader, _ = user(api, bearer, "catcher")
    slug = open_org(api, owner)
    join(api, slug, reader)
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]
    first = sent(api, owner, org_id, "Mot")
    sent(api, owner, org_id, "Hai")

    def unread_here() -> int:
        items = api.client.get(
            f"/organizations/{slug}/chat/unread", headers=reader
        ).json()["items"]
        return next(item["count"] for item in items if item["room_id"] == org_id)

    assert unread_here() == 2
    api.client.post(
        f"/rooms/{org_id}/read", headers=reader, json={"message_id": first["id"]}
    )
    assert unread_here() == 1


def test_history_pages_newest_first(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "pager_chat")
    slug = open_org(api, owner)
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]
    texts = [sent(api, owner, org_id, text)["id"] for text in ("a", "b", "c")]

    page_one = api.client.get(f"/rooms/{org_id}/messages?limit=2", headers=owner).json()
    page_two = api.client.get(
        f"/rooms/{org_id}/messages?limit=2&before={page_one['next_before']}",
        headers=owner,
    ).json()

    assert [item["id"] for item in page_one["items"]] == [texts[2], texts[1]]
    assert [item["id"] for item in page_two["items"]] == [texts[0]]
    assert page_two["next_before"] is None


def test_websocket_pushes_new_messages_to_subscribers(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "live")
    slug = open_org(api, owner)
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]
    socket_ticket = ticket(api, owner)

    with api.client.websocket_connect(f"/ws/chat?ticket={socket_ticket}") as socket:
        socket.send_json({"op": "subscribe", "room_id": org_id})
        assert socket.receive_json() == {"op": "subscribed", "room_id": org_id}
        socket.send_json({"op": "ping"})
        assert socket.receive_json() == {"op": "pong"}

        sent(api, owner, org_id, "Tin truc tiep")
        event: dict[str, Any] = socket.receive_json()

    assert event["type"] == "message.created"
    assert event["room_id"] == org_id
    assert event["message"]["body"] == "Tin truc tiep"


def test_managers_add_members_to_a_restricted_channel(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "adder")
    newcomer, newcomer_id = user(api, bearer, "newcomer")
    slug = open_org(api, owner)
    join(api, slug, newcomer)
    open_room = channel(api, owner, slug, "Mo rong")
    closed = channel(api, owner, slug, "Dong", visibility="restricted")

    refused = api.client.post(
        f"/chat/channels/{open_room['id']}/members",
        headers=owner,
        json={"user_ids": [newcomer_id]},
    )
    added = api.client.post(
        f"/chat/channels/{closed['id']}/members",
        headers=owner,
        json={"user_ids": [newcomer_id]},
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == "channel_not_restricted"
    assert added.status_code == 204
    assert messages(api, newcomer, closed["id"]) == []


def test_socket_hears_edits_reactions_and_deletes(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "editor_live")
    slug = open_org(api, owner)
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]
    message = sent(api, owner, org_id, "Ban nhap")

    with api.client.websocket_connect(
        f"/ws/chat?ticket={ticket(api, owner)}"
    ) as socket:
        socket.send_json({"op": "subscribe", "room_id": org_id})
        assert socket.receive_json()["op"] == "subscribed"

        api.client.patch(
            f"/messages/{message['id']}", headers=owner, json={"body": "Ban sua"}
        )
        edited = socket.receive_json()
        api.client.post(
            f"/messages/{message['id']}/reactions", headers=owner, json={"emoji": "+1"}
        )
        reacted = socket.receive_json()
        api.client.delete(f"/messages/{message['id']}", headers=owner)
        deleted = socket.receive_json()

    assert edited["type"] == "message.updated"
    assert edited["message"]["body"] == "Ban sua"
    assert reacted["message"]["reactions"] == [
        {"emoji": "+1", "count": 1, "mine": False}
    ]
    assert deleted == {
        "type": "message.deleted",
        "room_id": org_id,
        "message_id": message["id"],
        "topic": f"room:{org_id}",
    }


def test_channel_names_are_unique_while_live(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "namer")
    slug = open_org(api, owner)
    room = channel(api, owner, slug, "Chung")

    duplicate = api.client.post(
        f"/organizations/{slug}/chat/channels", headers=owner, json={"name": "CHUNG"}
    )
    api.client.post(f"/chat/channels/{room['id']}/archive", headers=owner)
    reused = api.client.post(
        f"/organizations/{slug}/chat/channels", headers=owner, json={"name": "Chung"}
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "channel_name_taken"
    assert reused.status_code == 201
