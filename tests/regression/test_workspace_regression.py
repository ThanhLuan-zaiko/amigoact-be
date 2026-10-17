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
    "updated_at", "revision_of", "visibility",
}
PAGE_FIELDS = {
    "items", "pinned", "total", "viewer_role", "viewer_permissions",
}
CHAT_PAGE_FIELDS = {
    "items", "next_cursor", "unread", "last_read_message_id",
    # Phase 2: dm-only peer read pointer for the double-check receipt.
    "peer_last_read_message_id",
    # Phase 3: pinned bar payload + the caller's mute flag.
    "pinned", "muted",
}
MESSAGE_FIELDS = {
    "message_id", "room_id", "author_id", "author_name", "body",
    "author_avatar_url",
    "created_at",
    # Phase 1: reply metadata, edit marker, embedded files.
    "reply_to_id", "reply_to_author", "reply_to_body", "edited_at",
    "attachments",
    # Phase 2: reaction tallies and @-mention entries.
    "reactions", "mentions",
}
INBOX_FIELDS = {"items"}
INBOX_ROOM_FIELDS = {
    "room_id", "kind", "org_id", "org_name", "title", "peer_id",
    "avatar_url", "last_message_id", "last_body", "last_author_name",
    "last_at", "unread", "sort_at",
    # Media-index phase: org slug for the community share link.
    "org_slug",
    # Phase 2: dm peer presence stamp for the "last seen" subtitle.
    "peer_last_seen_at",
    # Phase 3: muted rows keep the counter but stay dimmed/badgeless.
    "muted",
    # Channels: post gate + display label on channel rows only.
    "post_policy", "channel_kind",
}
INBOX_KINDS = {"general", "activity", "dm", "channel"}
CHANNEL_FIELDS = {
    "channel_id", "org_id", "name", "topic", "kind", "post_policy",
    "visibility", "created_by", "created_at", "archived_at",
}
CHANNEL_MEMBER_FIELDS = {"user_id", "full_name", "avatar_url", "added_at"}
MEDIA_PAGE_FIELDS = {"items", "next_cursor"}
MEDIA_ITEM_FIELDS = {
    "message_id", "kind", "media_id", "url", "mime", "name",
    "size_bytes", "author_id", "author_name", "author_avatar_url",
    "created_at",
}
MEDIA_AUTHOR_FIELDS = {
    "author_id", "author_name", "author_avatar_url", "kinds", "last_at",
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


async def test_chat_inbox_contract(client: AsyncClient) -> None:
    """Inbox rows keep their field names, kind enum and stable sort."""
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "rg-inbox"
    )
    await client.post(
        f"/orgs/{org_id}/chat/dm",
        json={"peer_id": member_id},
        headers=owner_h,
    )
    await client.post(
        f"/orgs/{org_id}/chat/messages",
        json={"body": "hi"},
        headers=member_h,
    )
    inbox = await client.get("/chat/inbox", headers=owner_h)
    assert inbox.status_code == 200
    body = inbox.json()
    assert set(body) == INBOX_FIELDS
    assert body["items"], "owner inbox must not be empty"
    for row in body["items"]:
        assert set(row) == INBOX_ROOM_FIELDS
        assert row["kind"] in INBOX_KINDS
        assert row["org_id"] == org_id
    sorted_rows = sorted(
        body["items"], key=lambda r: (r["sort_at"] or ""), reverse=True
    )
    assert [r["room_id"] for r in body["items"]] == [
        r["room_id"] for r in sorted_rows
    ]


async def test_channel_contract_and_error_codes(
    client: AsyncClient,
) -> None:
    """Channel rows freeze field names + the new error code envelope."""
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "rg-chan"
    )
    created = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "regression", "visibility": "restricted"},
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    assert set(created.json()) == CHANNEL_FIELDS
    cid = created.json()["channel_id"]

    listed = await client.get(
        f"/orgs/{org_id}/chat/channels", headers=owner_h
    )
    assert set(listed.json()) == {"items"}
    assert set(listed.json()["items"][0]) == CHANNEL_FIELDS

    dup = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "REGRESSION"},
        headers=owner_h,
    )
    assert (dup.status_code, dup.json()["code"]) == (
        409,
        "CHANNEL_NAME_TAKEN",
    )
    missing = await client.patch(
        f"/orgs/{org_id}/chat/channels/{org_id}",
        json={"topic": "x"},
        headers=owner_h,
    )
    assert (missing.status_code, missing.json()["code"]) == (
        404,
        "CHANNEL_NOT_FOUND",
    )

    await client.post(
        f"/orgs/{org_id}/chat/channels/{cid}/members",
        json={"user_id": member_id},
        headers=owner_h,
    )
    roster = await client.get(
        f"/orgs/{org_id}/chat/channels/{cid}/members", headers=member_h
    )
    assert set(roster.json()["items"][0]) == CHANNEL_MEMBER_FIELDS


async def test_shared_media_contract(client: AsyncClient) -> None:
    """Media-index page + item field names stay frozen for the panel."""
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "rg-media"
    )
    await client.post(
        f"/orgs/{org_id}/chat/messages",
        json={"body": "xem https://rg.example/doc"},
        headers=member_h,
    )
    page = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link", headers=owner_h
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert set(body) == MEDIA_PAGE_FIELDS
    assert len(body["items"]) == 1
    assert set(body["items"][0]) == MEDIA_ITEM_FIELDS
    assert body["items"][0]["kind"] == "link"
    assert body["items"][0]["url"] == "https://rg.example/doc"

    # Sender filter: authors list feeds the dropdown, author_id narrows
    # the tab listing — both contracts frozen.
    authors = await client.get(
        f"/chat/rooms/{org_id}/media/authors", headers=owner_h
    )
    assert authors.status_code == 200, authors.text
    arows = authors.json()["items"]
    assert len(arows) == 1
    assert set(arows[0]) == MEDIA_AUTHOR_FIELDS
    filtered = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link"
        f"&author_id={arows[0]['author_id']}",
        headers=owner_h,
    )
    assert filtered.status_code == 200, filtered.text
    assert len(filtered.json()["items"]) == 1


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
