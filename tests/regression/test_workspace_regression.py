"""Regression: freeze the board/chat contracts and edge behaviors.

Locks: response field names for PostPageResponse/ChatPageResponse, the
{code, message} error envelope on member gates, the sender-read rule on
own chat sends, and bb: bucket cursors surviving malformed input.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import (
    _headers,
    _org_with_member,
    _token,
)

POST_FIELDS = {
    "post_id", "org_id", "author_id", "author_name", "kind", "title",
    "body", "pinned_at", "edited_at", "media", "comment_count",
    "created_at",
    # Article fields (block editor, drafts, trash, revisions).
    "status", "blocks", "cover_media_id", "published_at", "deleted_at",
    "updated_at", "revision_of",
}
PAGE_FIELDS = {
    "items", "pinned", "total", "viewer_role", "viewer_permissions",
}
CHAT_PAGE_FIELDS = {
    "items", "next_cursor", "unread", "last_read_message_id",
}
MESSAGE_FIELDS = {
    "message_id", "room_id", "author_id", "author_name", "body",
    "created_at",
}


async def test_post_page_contract(client: AsyncClient) -> None:
    """Board page and post rows keep their public field names."""
    org_id, owner_h, _, _ = await _org_with_member(client, "rg-post")
    made = await client.post(
        f"/orgs/{org_id}/posts",
        json={"kind": "discussion", "body": "x"},
        headers=owner_h,
    )
    assert set(made.json()) == POST_FIELDS
    page = await client.get(f"/orgs/{org_id}/posts", headers=owner_h)
    assert set(page.json()) == PAGE_FIELDS
    assert page.json()["viewer_role"] == "owner"
    # Owner carries the whole permission catalog implicitly (same rule as
    # member_service.list_members); an empty list would lock owner UI.
    assert "post:announce" in page.json()["viewer_permissions"]
    assert "post:manage" in page.json()["viewer_permissions"]


async def test_legacy_post_and_static_routes(client: AsyncClient) -> None:
    """Body-only posts still publish; /drafts and /trash are not shadowed
    by /posts/{post_id}; plain DELETE stays 204 + 404 on read (now soft)."""
    org_id, owner_h, _, _ = await _org_with_member(client, "rg-art")
    base = f"/orgs/{org_id}/posts"
    made = await client.post(
        base, json={"kind": "discussion", "body": "x"}, headers=owner_h
    )
    assert made.status_code == 201
    assert made.json()["status"] == "published"
    assert made.json()["blocks"] == []
    for path in ("drafts", "trash"):
        page = await client.get(f"{base}/{path}", headers=owner_h)
        assert page.status_code == 200
        assert set(page.json()) == PAGE_FIELDS
    post_id = made.json()["post_id"]
    deleted = await client.delete(f"{base}/{post_id}", headers=owner_h)
    assert deleted.status_code == 204
    ghost = await client.get(f"{base}/{post_id}", headers=owner_h)
    assert ghost.status_code == 404
    assert ghost.json()["code"] == "NOT_FOUND"


async def test_chat_page_contract_and_sender_read(
    client: AsyncClient,
) -> None:
    """Chat page keeps badge fields; own sends never add unread."""
    org_id, owner_h, _, _ = await _org_with_member(client, "rg-chat")
    sent = await client.post(
        f"/orgs/{org_id}/chat/messages",
        json={"body": "hi"},
        headers=owner_h,
    )
    assert set(sent.json()) == MESSAGE_FIELDS
    page = await client.get(
        f"/orgs/{org_id}/chat/messages", headers=owner_h
    )
    body = page.json()
    assert set(body) == CHAT_PAGE_FIELDS
    assert body["unread"] == 0
    assert body["last_read_message_id"] == sent.json()["message_id"]


async def test_member_gate_error_envelope(client: AsyncClient) -> None:
    """Non-members get the shared FORBIDDEN code on every workspace route."""
    org_id, _, _, _ = await _org_with_member(client, "rg-gate")
    stranger = await _token(client, "rg-gate-out@x.com", "0912347005")
    headers = _headers(stranger)
    for method, url in (
        ("get", f"/orgs/{org_id}/posts"),
        ("get", f"/orgs/{org_id}/chat/messages"),
        ("get", f"/orgs/{org_id}/chat/unread"),
    ):
        response = await getattr(client, method)(url, headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"
    sent = await client.post(
        f"/orgs/{org_id}/chat/messages",
        json={"body": "x"},
        headers=headers,
    )
    assert sent.status_code == 403
    assert sent.json()["code"] == "FORBIDDEN"


async def test_malformed_cursors_do_not_500(client: AsyncClient) -> None:
    """Garbage params degrade cleanly: ignored extras, 422 on bad page."""
    org_id, owner_h, _, _ = await _org_with_member(client, "rg-cursor")
    posts = await client.get(
        f"/orgs/{org_id}/posts?cursor=not-a-uuid", headers=owner_h
    )
    assert posts.status_code == 200
    bad_page = await client.get(
        f"/orgs/{org_id}/posts?page=abc", headers=owner_h
    )
    assert bad_page.status_code == 422
    chat = await client.get(
        f"/orgs/{org_id}/chat/messages?cursor=bb:garbage",
        headers=owner_h,
    )
    assert chat.status_code == 200
    chat = await client.get(
        f"/orgs/{org_id}/chat/messages?cursor=junk",
        headers=owner_h,
    )
    assert chat.status_code == 200
