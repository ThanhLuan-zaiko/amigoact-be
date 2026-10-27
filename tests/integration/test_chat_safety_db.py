"""Integration tests: chat timeouts, attachment policy and @all over HTTP."""

from __future__ import annotations

import base64

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def _send(client, org_id, headers, body):  # noqa: ANN001, ANN202
    return await client.post(
        f"/chat/rooms/{org_id}/messages", json={"body": body}, headers=headers
    )


async def test_timeout_blocks_and_lifts(client: AsyncClient) -> None:
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "cs-timeout"
    )
    base = f"/orgs/{org_id}/chat/safety"
    assert (await _send(client, org_id, member_h, "hi")).status_code == 201

    denied = await client.put(
        f"{base}/timeouts/{member_id}", json={"minutes": 5}, headers=member_h
    )
    assert denied.status_code == 403, denied.text
    muted = await client.put(
        f"{base}/timeouts/{member_id}",
        json={"minutes": 10, "reason": "spam"},
        headers=owner_h,
    )
    assert muted.status_code == 200, muted.text
    assert muted.json()["reason"] == "spam"

    blocked = await _send(client, org_id, member_h, "again")
    assert (blocked.status_code, blocked.json()["code"]) == (403, "CHAT_TIMED_OUT")
    mine = await client.get(base, headers=member_h)
    assert mine.json()["my_timeout_until"] is not None
    assert mine.json()["timeouts"] == []
    staff = await client.get(base, headers=owner_h)
    assert [t["user_id"] for t in staff.json()["timeouts"]] == [member_id]

    lifted = await client.delete(f"{base}/timeouts/{member_id}", headers=owner_h)
    assert lifted.status_code == 204, lifted.text
    assert (await _send(client, org_id, member_h, "free")).status_code == 201
    assert (await client.get(base, headers=owner_h)).json()["timeouts"] == []


async def test_attachment_policy_and_all_mention(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "cs-attach")
    base = f"/orgs/{org_id}/chat/safety"
    upload = lambda h: client.post(  # noqa: E731
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("dot.png", _PNG, "image/png")},
        headers=h,
    )
    assert (await upload(member_h)).status_code == 201

    policy = await client.put(
        f"{base}/attachments", json={"restricted": True}, headers=member_h
    )
    assert policy.status_code == 403
    on = await client.put(
        f"{base}/attachments", json={"restricted": True}, headers=owner_h
    )
    assert on.json() == {"attach_restricted": True}
    blocked = await upload(member_h)
    assert (blocked.status_code, blocked.json()["code"]) == (
        403, "CHAT_ATTACH_RESTRICTED",
    )
    assert (await upload(owner_h)).status_code == 201

    # A member may not @all; the owner's @all is stored as a mention.
    plain = await _send(client, org_id, member_h, "hey @all")
    assert plain.json()["mentions"] == []
    loud = await _send(client, org_id, owner_h, "meeting @all at 7")
    assert [m["name"] for m in loud.json()["mentions"]] == ["all"]
