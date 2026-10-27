"""Integration: members without post permissions cannot write."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member


async def test_member_without_post_permissions_cannot_write(
    client: AsyncClient,
) -> None:
    """A default member reads the board but cannot write, publish or comment."""
    org_id, owner_h, member_h, _ = await _org_with_member(client, "ws-nowrite")
    base = f"/orgs/{org_id}/posts"
    for body in (
        {"kind": "discussion", "body": "x"},
        {"kind": "discussion", "body": "x", "status": "draft"},
    ):
        denied = await client.post(base, json=body, headers=member_h)
        assert denied.status_code == 403, denied.text
    assert (await client.get(base, headers=member_h)).status_code == 200
    post = await client.post(
        base, json={"kind": "discussion", "body": "hi"}, headers=owner_h
    )
    assert post.status_code == 201, post.text
    comment = await client.post(
        f"{base}/{post.json()['post_id']}/comments",
        json={"body": "hey"},
        headers=member_h,
    )
    assert comment.status_code == 403, comment.text
