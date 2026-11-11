from tests.activity_helpers import Bearer, Headers, user
from tests.chat_helpers import channel, messages, send, sent
from tests.conftest import ApiContext
from tests.post_helpers import join, open_org


def _org_id(api: ApiContext, headers: Headers, slug: str) -> str:
    org_id: str = api.client.get(f"/organizations/{slug}", headers=headers).json()["id"]
    return org_id


def test_outsider_cannot_read_or_write_the_general_room(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "closed")
    outsider, _ = user(api, bearer, "knocking")
    slug = open_org(api, owner)
    org_id = _org_id(api, owner, slug)
    sent(api, owner, org_id, "Noi bo")

    read = api.client.get(f"/rooms/{org_id}/messages", headers=outsider)
    write = send(api, outsider, org_id, "Xin vao")

    assert read.status_code == 404
    assert read.json()["detail"] == "room_not_found"
    assert write.status_code == 404
    assert (
        api.client.get(
            f"/organizations/{slug}/chat/channels", headers=outsider
        ).status_code
        == 403
    )


def test_restricted_channel_is_hidden_from_everyone_outside_it(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "vault")
    insider, insider_id = user(api, bearer, "keyholder")
    outsider, _ = user(api, bearer, "passerby")
    slug = open_org(api, owner)
    join(api, slug, insider)
    join(api, slug, outsider)
    room = channel(
        api, owner, slug, "Kin", visibility="restricted", member_ids=[insider_id]
    )
    sent(api, insider, room["id"], "Bi mat")

    assert (
        api.client.get(f"/rooms/{room['id']}/messages", headers=outsider).status_code
        == 404
    )
    assert (
        api.client.get(f"/rooms/{room['id']}/pins", headers=outsider).status_code == 404
    )
    assert send(api, outsider, room["id"], "Lot vao").status_code == 404
    listed = api.client.get(
        f"/organizations/{slug}/chat/channels", headers=outsider
    ).json()
    assert room["id"] not in [item["id"] for item in listed["items"]]


def test_only_managers_create_archive_and_manage_channels(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "chief")
    member, member_id = user(api, bearer, "junior")
    slug = open_org(api, owner)
    join(api, slug, member)
    room = channel(api, owner, slug, "Phong chung")

    create = api.client.post(
        f"/organizations/{slug}/chat/channels", headers=member, json={"name": "Rieng"}
    )
    archive = api.client.post(f"/chat/channels/{room['id']}/archive", headers=member)
    add = api.client.post(
        f"/chat/channels/{room['id']}/members",
        headers=member,
        json={"user_ids": [member_id]},
    )

    assert create.status_code == 403
    assert archive.status_code == 403
    assert add.status_code == 403


def test_members_must_be_active_members_and_restricted_channels_only(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "setup")
    _, stranger_id = user(api, bearer, "stranger")
    slug = open_org(api, owner)

    stranger_in_restricted = api.client.post(
        f"/organizations/{slug}/chat/channels",
        headers=owner,
        json={"name": "Kin", "visibility": "restricted", "member_ids": [stranger_id]},
    )
    members_on_open = api.client.post(
        f"/organizations/{slug}/chat/channels",
        headers=owner,
        json={"name": "Mo", "visibility": "open", "member_ids": [stranger_id]},
    )

    assert stranger_in_restricted.status_code == 422
    assert "not_a_member" in stranger_in_restricted.text
    assert members_on_open.status_code == 422
    assert "needs_restricted_channel" in members_on_open.text


def test_archived_channel_stays_readable_but_closed(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "closer")
    member, _ = user(api, bearer, "reader_only")
    slug = open_org(api, owner)
    join(api, slug, member)
    room = channel(api, owner, slug, "Cu")
    sent(api, owner, room["id"], "Lich su")
    api.client.post(f"/chat/channels/{room['id']}/archive", headers=owner)

    assert messages(api, member, room["id"])[0]["body"] == "Lich su"
    assert send(api, member, room["id"], "Them").status_code == 409
    again = api.client.post(f"/chat/channels/{room['id']}/archive", headers=owner)
    assert again.status_code == 409


def test_members_cannot_edit_or_delete_others_or_pin(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "moderator_r")
    member, _ = user(api, bearer, "plain_r")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = _org_id(api, owner, slug)
    message = sent(api, owner, org_id, "Thong bao")

    edit = api.client.patch(
        f"/messages/{message['id']}", headers=member, json={"body": "Sua"}
    )
    delete = api.client.delete(f"/messages/{message['id']}", headers=member)
    pin = api.client.post(f"/rooms/{org_id}/pins/{message['id']}", headers=member)

    assert edit.status_code == 403
    assert edit.json()["detail"] == "message_forbidden"
    assert delete.status_code == 403
    assert pin.status_code == 403


def test_reply_cannot_quote_a_message_from_another_room(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "quoter")
    slug = open_org(api, owner)
    org_id = _org_id(api, owner, slug)
    room = channel(api, owner, slug, "Khac")
    elsewhere = sent(api, owner, room["id"], "Phong khac")

    response = send(api, owner, org_id, "Tra loi", reply_to_id=elsewhere["id"])

    assert response.status_code == 422
    assert "not_in_room" in response.text


def test_direct_messages_are_private_to_the_pair(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "pair_a")
    peer, peer_id = user(api, bearer, "pair_b")
    third, _ = user(api, bearer, "pair_c")
    slug = open_org(api, owner)
    join(api, slug, peer)
    join(api, slug, third)
    room_id = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=owner, json={"user_id": peer_id}
    ).json()["room_id"]
    sent(api, owner, room_id, "Chi hai nguoi")

    assert (
        api.client.get(f"/rooms/{room_id}/messages", headers=third).status_code == 404
    )
    assert send(api, third, room_id, "Xen vao").status_code == 404
    listed = api.client.get(f"/organizations/{slug}/chat/dms", headers=third).json()
    assert listed["items"] == []


def test_dm_peer_cannot_delete_the_other_persons_message(
    api: ApiContext, bearer: Bearer
) -> None:
    """Pinning is shared in a DM, deleting is not. The peer could once remove it."""
    owner, _ = user(api, bearer, "dm_keep_a")
    peer, peer_id = user(api, bearer, "dm_keep_b")
    slug = open_org(api, owner)
    join(api, slug, peer)
    room_id = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=owner, json={"user_id": peer_id}
    ).json()["room_id"]
    from_owner = sent(api, owner, room_id, "Dung xoa")
    from_peer = sent(api, peer, room_id, "Cua toi")

    by_peer = api.client.delete(f"/messages/{from_owner['id']}", headers=peer)
    # Managing the organization gives no delete right inside a DM either.
    by_owner = api.client.delete(f"/messages/{from_peer['id']}", headers=owner)

    assert by_peer.status_code == 403
    assert by_peer.json()["detail"] == "message_forbidden"
    assert by_owner.status_code == 403
    assert by_owner.json()["detail"] == "message_forbidden"
    kept = [item["id"] for item in messages(api, peer, room_id)]
    assert sorted(kept) == sorted([from_owner["id"], from_peer["id"]])


def test_dm_needs_two_active_members(api: ApiContext, bearer: Bearer) -> None:
    owner, owner_id = user(api, bearer, "opener")
    _, outsider_id = user(api, bearer, "not_joined")
    slug = open_org(api, owner)

    to_self = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=owner, json={"user_id": owner_id}
    )
    to_outsider = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=owner, json={"user_id": outsider_id}
    )

    assert "self_dm" in to_self.text
    assert "not_a_member" in to_outsider.text


def test_leaving_the_organization_closes_its_direct_messages(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "host_dm")
    leaver, leaver_id = user(api, bearer, "leaver_dm")
    slug = open_org(api, owner)
    join(api, slug, leaver)
    room_id = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=owner, json={"user_id": leaver_id}
    ).json()["room_id"]

    assert (
        api.client.delete(
            f"/organizations/{slug}/membership", headers=leaver
        ).status_code
        == 204
    )

    assert (
        api.client.get(f"/rooms/{room_id}/messages", headers=leaver).status_code == 404
    )


def test_message_body_limits(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "limits")
    slug = open_org(api, owner)
    org_id = _org_id(api, owner, slug)

    too_long = send(api, owner, org_id, "x" * 2001)
    blank = send(api, owner, org_id, "   ")
    control = send(api, owner, org_id, "a\x00b")

    assert too_long.status_code == 422
    assert blank.status_code == 422
    assert control.status_code == 422


def test_read_marker_must_point_into_the_same_room(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "marker")
    slug = open_org(api, owner)
    org_id = _org_id(api, owner, slug)
    room = channel(api, owner, slug, "Ben")
    elsewhere = sent(api, owner, room["id"], "Khac")

    response = api.client.post(
        f"/rooms/{org_id}/read", headers=owner, json={"message_id": elsewhere["id"]}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "message_not_found"


def test_reaction_emoji_length_is_limited(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "reactor")
    slug = open_org(api, owner)
    org_id = _org_id(api, owner, slug)
    message = sent(api, owner, org_id, "Tha tim")

    response = api.client.post(
        f"/messages/{message['id']}/reactions", headers=owner, json={"emoji": "x" * 17}
    )

    assert response.status_code == 422
