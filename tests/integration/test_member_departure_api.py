from tests.activity_helpers import Bearer, user
from tests.chat_helpers import sent, ticket
from tests.conftest import ApiContext
from tests.notification_helpers import heard_nothing, next_frame
from tests.post_helpers import join, open_org


def org_id(api: ApiContext, slug: str, headers: dict[str, str]) -> str:
    value: str = api.client.get(f"/organizations/{slug}", headers=headers).json()["id"]
    return value


def test_leaving_tells_the_owner_and_admins_at_once(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    admin, admin_id = user(api, bearer, "admin")
    member, member_id = user(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, admin)
    join(api, slug, member)
    api.client.patch(
        f"/organizations/{slug}/members/{admin_id}",
        headers=owner,
        json={"role": "admin"},
    )

    with (
        api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, owner)}") as o,
        api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, admin)}") as a,
    ):
        left = api.client.delete(f"/organizations/{slug}/membership", headers=member)
        to_owner = next_frame(o)
        to_admin = next_frame(a)

    assert left.status_code == 204
    for frame in (to_owner, to_admin):
        assert frame["type"] == "notification.created"
        assert frame["notification"]["type"] == "member_left"
        assert frame["notification"]["data"]["organization_slug"] == slug
        assert frame["notification"]["data"]["member_id"] == member_id


def test_removal_tells_the_removed_member(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, member)

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, member)}") as ws:
        removed = api.client.delete(
            f"/organizations/{slug}/members/{member_id}", headers=owner
        )
        frame = next_frame(ws)

    assert removed.status_code == 204
    assert frame["notification"]["type"] == "membership_removed"
    assert frame["notification"]["data"]["organization_slug"] == slug


def test_leaving_admin_is_not_told_about_themself(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    admin, admin_id = user(api, bearer, "admin")
    slug = open_org(api, owner)
    join(api, slug, admin)
    api.client.patch(
        f"/organizations/{slug}/members/{admin_id}",
        headers=owner,
        json={"role": "admin"},
    )
    room = org_id(api, slug, owner)

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, admin)}") as ws:
        ws.send_json({"op": "subscribe", "room_id": room})
        assert ws.receive_json()["op"] == "subscribed"
        api.client.delete(f"/organizations/{slug}/membership", headers=admin)
        assert next_frame(ws) == {"op": "revoked", "room_id": room}
        assert heard_nothing(ws)

    items = api.client.get("/notifications", headers=owner).json()["items"]
    assert [item["type"] for item in items] == ["member_left"]
    sent(api, owner, room, "Still works")
