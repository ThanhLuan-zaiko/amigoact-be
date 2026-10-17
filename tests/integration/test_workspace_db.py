"""Integration tests: org board + chat endpoints over HTTP."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Ws User",
        },
    )
    assert response.status_code == 201, response.text
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _org_with_member(
    client: AsyncClient, slug: str
) -> tuple[str, dict[str, str], dict[str, str], str]:
    """Invite-flow org: owner + one accepted member + headers."""
    owner = await _token(client, f"{slug}-own@x.com", "0912347001")
    owner_h = _headers(owner)
    created = await client.post(
        "/orgs",
        json={
            "name": f"Name {slug}",
            "slug": slug,
            "description": "D",
            "kind": "club",
            "join_policy": "invite",
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]
    member = await _token(client, f"{slug}-mem@x.com", "0912347002")
    member_h = _headers(member)
    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": f"{slug}-mem@x.com"},
        headers=owner_h,
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=member_h
    )
    assert accepted.status_code == 200, accepted.text
    return org_id, owner_h, member_h, invited.json()["user_id"]


async def test_board_flow_with_roles(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "ws-board"
    )
    outsider = await _token(client, "ws-board-out@x.com", "0912347003")
    outsider_h = _headers(outsider)

    made = await client.post(
        f"/orgs/{org_id}/posts",
        json={"kind": "discussion", "body": "first"},
        headers=member_h,
    )
    assert made.status_code == 201, made.text
    post = made.json()
    assert post["kind"] == "discussion" and post["author_name"]

    denied = await client.post(
        f"/orgs/{org_id}/posts",
        json={"kind": "announcement", "title": "T", "body": "b"},
        headers=member_h,
    )
    assert denied.status_code == 403

    ann = await client.post(
        f"/orgs/{org_id}/posts",
        json={"kind": "announcement", "title": "Hi", "body": "b"},
        headers=owner_h,
    )
    assert ann.status_code == 201, ann.text

    blocked = await client.get(f"/orgs/{org_id}/posts", headers=outsider_h)
    assert blocked.status_code == 403

    listed = await client.get(f"/orgs/{org_id}/posts", headers=member_h)
    assert listed.status_code == 200
    page = listed.json()
    assert page["viewer_role"] == "member"
    assert {p["post_id"] for p in page["items"]} == {
        post["post_id"], ann.json()["post_id"]
    }

    # Only managers pin; the rail ships on the first page.
    pin_denied = await client.post(
        f"/orgs/{org_id}/posts/{post['post_id']}/pin", headers=member_h
    )
    assert pin_denied.status_code == 403
    pinned = await client.post(
        f"/orgs/{org_id}/posts/{post['post_id']}/pin", headers=owner_h
    )
    assert pinned.status_code == 200
    listed = await client.get(f"/orgs/{org_id}/posts", headers=member_h)
    assert [p["post_id"] for p in listed.json()["pinned"]] == [
        post["post_id"]
    ]

    comment = await client.post(
        f"/orgs/{org_id}/posts/{post['post_id']}/comments",
        json={"body": "nice"},
        headers=owner_h,
    )
    assert comment.status_code == 201, comment.text
    thread = await client.get(
        f"/orgs/{org_id}/posts/{post['post_id']}/comments",
        headers=member_h,
    )
    assert [c["body"] for c in thread.json()["items"]] == ["nice"]

    deleted = await client.delete(
        f"/orgs/{org_id}/posts/{post['post_id']}", headers=owner_h
    )
    assert deleted.status_code == 204
    ghost = await client.get(
        f"/orgs/{org_id}/posts/{post['post_id']}", headers=owner_h
    )
    assert ghost.status_code == 404


async def test_chat_flow_with_unread_and_moderation(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "ws-chat"
    )
    outsider = await _token(client, "ws-chat-out@x.com", "0912347004")
    outsider_h = _headers(outsider)

    blocked = await client.post(
        f"/orgs/{org_id}/chat/messages",
        json={"body": "hi"},
        headers=outsider_h,
    )
    assert blocked.status_code == 403

    for text in ("m1", "m2"):
        sent = await client.post(
            f"/orgs/{org_id}/chat/messages",
            json={"body": text},
            headers=member_h,
        )
        assert sent.status_code == 201, sent.text

    owner_view = await client.get(
        f"/orgs/{org_id}/chat/messages", headers=owner_h
    )
    assert owner_view.status_code == 200
    page = owner_view.json()
    assert [m["body"] for m in page["items"]] == ["m1", "m2"]
    assert page["unread"] == 2

    owner_msg = await client.post(
        f"/orgs/{org_id}/chat/messages",
        json={"body": "reply"},
        headers=owner_h,
    )
    assert owner_msg.status_code == 201

    badge = await client.get(
        f"/orgs/{org_id}/chat/unread", headers=member_h
    )
    assert badge.json()["unread"] == 1
    read = await client.post(
        f"/orgs/{org_id}/chat/read",
        json={"message_id": owner_msg.json()["message_id"]},
        headers=member_h,
    )
    assert read.status_code == 200
    again = await client.get(
        f"/orgs/{org_id}/chat/messages", headers=member_h
    )
    assert again.json()["unread"] == 0

    member_msgs = await client.get(
        f"/orgs/{org_id}/chat/messages", headers=member_h
    )
    first_id = member_msgs.json()["items"][0]["message_id"]
    denied = await client.delete(
        f"/orgs/{org_id}/chat/messages/{first_id}", headers=outsider_h
    )
    assert denied.status_code == 403
    removed = await client.delete(
        f"/orgs/{org_id}/chat/messages/{first_id}", headers=owner_h
    )
    assert removed.status_code == 204


async def test_dm_room_flow_and_isolation(client: AsyncClient) -> None:
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "ws-dm"
    )
    # A second member who never joins the dm room.
    third = await _token(client, "ws-dm-third@x.com", "0912347006")
    third_h = _headers(third)
    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "ws-dm-third@x.com"},
        headers=owner_h,
    )
    assert invited.status_code == 201, invited.text
    await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=third_h
    )
    stranger = await _token(client, "ws-dm-out@x.com", "0912347007")
    stranger_h = _headers(stranger)

    # Invited members can open a dm with the owner; the room converges.
    opened = await client.post(
        f"/orgs/{org_id}/chat/dm",
        json={"peer_id": member_id},
        headers=owner_h,
    )
    assert opened.status_code == 201, opened.text
    room_id = opened.json()["room_id"]
    assert opened.json()["peer_name"] == "Ws User"

    # A stranger outside the org cannot open a dm into it.
    blocked = await client.post(
        f"/orgs/{org_id}/chat/dm",
        json={"peer_id": member_id},
        headers=stranger_h,
    )
    assert blocked.status_code == 403

    sent = await client.post(
        f"/chat/rooms/{room_id}/messages",
        json={"body": "secret"},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["room_id"] == room_id

    page = await client.get(
        f"/chat/rooms/{room_id}/messages", headers=owner_h
    )
    assert [m["body"] for m in page.json()["items"]] == ["secret"]
    assert page.json()["unread"] == 1

    # The peer's dm inbox exposes exactly this room.
    inbox = await client.get(
        f"/orgs/{org_id}/chat/dm", headers=member_h
    )
    assert [r["room_id"] for r in inbox.json()["items"]] == [room_id]

    # A member who is not a participant gets the generic 404 - the room
    # does not resolve for them, so its existence stays hidden.
    hidden = await client.get(
        f"/chat/rooms/{room_id}/messages", headers=third_h
    )
    assert hidden.status_code == 404


async def test_activity_room_flow(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "ws-act"
    )
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Room Activity",
            "description": "d",
            "location": "X",
            "city": "X",
            "is_remote": False,
            "start_at": "2030-06-01T08:00:00Z",
            "end_at": "2030-06-01T12:00:00Z",
            "hours_awarded": 2.0,
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    activity_id = created.json()["id"]

    sent = await client.post(
        f"/chat/rooms/{activity_id}/messages",
        json={"body": "logistics?"},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text

    page = await client.get(
        f"/chat/rooms/{activity_id}/messages", headers=owner_h
    )
    assert [m["body"] for m in page.json()["items"]] == ["logistics?"]
    assert page.json()["unread"] == 1

    # Room messages never leak into the general org room.
    general = await client.get(
        f"/orgs/{org_id}/chat/messages", headers=owner_h
    )
    assert general.json()["items"] == []


async def test_member_roster_carries_avatar_url(client: AsyncClient) -> None:
    """Uploaded profile avatars surface on the org member roster."""
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "ws-rava"
    )
    uploaded = await client.post(
        "/profiles/me/avatar",
        files={"file": ("me.png", b"\x89PNG" + b"0" * 100, "image/png")},
        headers=member_h,
    )
    assert uploaded.status_code == 200, uploaded.text
    roster = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    assert roster.status_code == 200, roster.text
    row = next(
        item for item in roster.json()["items"]
        if item["user_id"] == member_id
    )
    assert row["avatar_url"] == uploaded.json()["avatar_url"]
