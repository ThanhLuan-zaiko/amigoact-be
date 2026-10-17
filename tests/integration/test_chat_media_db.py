"""Integration tests: org_room_media index and its /media endpoint."""

from __future__ import annotations

import base64

from httpx import AsyncClient

from tests.integration.test_workspace_db import (
    _headers,
    _org_with_member,
    _token,
)

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def test_media_tabs_index_links_and_attachments(
    client: AsyncClient,
) -> None:
    """Send -> index; every tab authorizes members and joins authors."""
    org_id, owner_h, member_h, _mid = await _org_with_member(
        client, "ws-media"
    )

    uploaded = await client.post(
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("dot.png", _PNG, "image/png")},
        headers=member_h,
    )
    assert uploaded.status_code == 201, uploaded.text
    media_id = uploaded.json()["media_id"]

    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={
            "body": "anh + https://example.com/doc",
            "attachment_ids": [media_id],
        },
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    message_id = sent.json()["message_id"]

    images = await client.get(
        f"/chat/rooms/{org_id}/media?kind=image", headers=owner_h
    )
    assert images.status_code == 200, images.text
    rows = images.json()["items"]
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "image"
    assert row["media_id"] == media_id
    assert row["message_id"] == message_id
    assert row["author_id"] and row["author_name"]
    assert row["created_at"] is not None
    assert row["url"].startswith("/media/")

    links = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link", headers=member_h
    )
    assert links.status_code == 200, links.text
    lrows = links.json()["items"]
    assert len(lrows) == 1
    # The API returns the decrypted URL even though it sits in the index
    # as ciphertext at rest.
    assert lrows[0]["url"] == "https://example.com/doc"

    for empty_kind in ("video", "file"):
        empty = await client.get(
            f"/chat/rooms/{org_id}/media?kind={empty_kind}",
            headers=owner_h,
        )
        assert empty.status_code == 200
        assert empty.json()["items"] == []
        assert empty.json()["next_cursor"] is None

    # kind is validated; outsiders get the generic room 404.
    bad = await client.get(
        f"/chat/rooms/{org_id}/media?kind=audio", headers=owner_h
    )
    assert bad.status_code == 422
    outsider_h = _headers(
        await _token(client, "ws-media-out@x.com", "0912347004")
    )
    denied = await client.get(
        f"/chat/rooms/{org_id}/media?kind=image", headers=outsider_h
    )
    assert denied.status_code in (403, 404)


async def test_media_index_follows_edit_and_delete(
    client: AsyncClient,
) -> None:
    """Edits rebuild only link rows; deletes drop every index row."""
    org_id, owner_h, member_h, _mid = await _org_with_member(
        client, "ws-media2"
    )
    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "see https://old.example"},
        headers=member_h,
    )
    message_id = sent.json()["message_id"]

    edited = await client.patch(
        f"/chat/rooms/{org_id}/messages/{message_id}",
        json={"body": "see https://new.example and https://x.example"},
        headers=member_h,
    )
    assert edited.status_code == 200, edited.text

    links = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link", headers=owner_h
    )
    urls = {row["url"] for row in links.json()["items"]}
    # Within one message rows come back item_index-descending, so the
    # contract is the set of links, not their intra-message order.
    assert urls == {"https://new.example", "https://x.example"}
    assert all(row["message_id"] == message_id for row in links.json()["items"])

    deleted = await client.delete(
        f"/chat/rooms/{org_id}/messages/{message_id}", headers=member_h
    )
    assert deleted.status_code in (200, 204)
    after = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link", headers=owner_h
    )
    assert after.json()["items"] == []


async def test_media_pagination_cursor(client: AsyncClient) -> None:
    """limit + next_cursor page the link tab newest-first."""
    org_id, owner_h, _member_h, _mid = await _org_with_member(
        client, "ws-mediapg"
    )
    for i in range(4):
        sent = await client.post(
            f"/chat/rooms/{org_id}/messages",
            json={"body": f"https://ex{i}.example/"},
            headers=owner_h,
        )
        assert sent.status_code == 201, sent.text

    first = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link&limit=2",
        headers=owner_h,
    )
    assert first.status_code == 200, first.text
    page = first.json()
    assert [r["url"] for r in page["items"]] == [
        "https://ex3.example/",
        "https://ex2.example/",
    ]
    assert page["next_cursor"]

    second = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link&limit=2"
        f"&cursor={page['next_cursor']}",
        headers=owner_h,
    )
    urls = [r["url"] for r in second.json()["items"]]
    assert urls == ["https://ex1.example/", "https://ex0.example/"]


async def test_media_author_filter_and_authors_endpoint(
    client: AsyncClient,
) -> None:
    """author_id narrows a tab; /media/authors lists real senders only."""
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "ws-mediaauth"
    )
    for headers, body in (
        (owner_h, "https://owner.example/1"),
        (member_h, "https://member.example/1"),
    ):
        sent = await client.post(
            f"/chat/rooms/{org_id}/messages",
            json={"body": body},
            headers=headers,
        )
        assert sent.status_code == 201, sent.text

    authors = await client.get(
        f"/chat/rooms/{org_id}/media/authors", headers=owner_h
    )
    assert authors.status_code == 200, authors.text
    rows = authors.json()["items"]
    assert len(rows) == 2
    for row in rows:
        assert row["author_id"] and row["author_name"]
        assert row["kinds"] == ["link"]
        assert row["last_at"] is not None

    filtered = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link&author_id={member_id}",
        headers=owner_h,
    )
    assert filtered.status_code == 200, filtered.text
    frows = filtered.json()["items"]
    assert len(frows) == 1
    assert frows[0]["url"] == "https://member.example/1"
    assert frows[0]["author_id"] == member_id

    outsiders = await client.get(
        f"/chat/rooms/{org_id}/media/authors",
        headers=_headers(
            await _token(client, "ws-mediaauth-out@x.com", "0912347005")
        ),
    )
    assert outsiders.status_code in (403, 404)


async def test_media_author_presence_dropped_with_last_item(
    client: AsyncClient,
) -> None:
    """Deleting a sender's only indexed item removes them from the
    filter's option list."""
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "ws-mediaprune"
    )
    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "https://member.example/only"},
        headers=member_h,
    )
    message_id = sent.json()["message_id"]
    await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "https://owner.example/stay"},
        headers=owner_h,
    )

    deleted = await client.delete(
        f"/chat/rooms/{org_id}/messages/{message_id}", headers=member_h
    )
    assert deleted.status_code in (200, 204)

    authors = await client.get(
        f"/chat/rooms/{org_id}/media/authors", headers=owner_h
    )
    author_ids = [r["author_id"] for r in authors.json()["items"]]
    assert len(author_ids) == 1
    assert member_id not in author_ids
    filtered = await client.get(
        f"/chat/rooms/{org_id}/media?kind=link&author_id={member_id}",
        headers=owner_h,
    )
    assert filtered.json()["items"] == []


async def test_inbox_rooms_carry_org_slug(client: AsyncClient) -> None:
    """The info panel builds /orgs/{slug} share links from inbox rows."""
    org_id, owner_h, _member_h, _mid = await _org_with_member(
        client, "ws-slug"
    )
    inbox = await client.get("/chat/inbox", headers=owner_h)
    assert inbox.status_code == 200, inbox.text
    row = next(
        item for item in inbox.json()["items"] if item["room_id"] == org_id
    )
    assert row["org_slug"] == "ws-slug"
