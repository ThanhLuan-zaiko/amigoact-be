"""Integration: board posts share the org tag catalog."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member


def _slugs(body: dict) -> list[str]:
    return [tag["slug"] for tag in body["tags"]]


async def _catalog_row(
    client: AsyncClient, org_id: str, headers: dict[str, str], slug: str
) -> dict:
    page = await client.get(f"/orgs/{org_id}/tags", headers=headers)
    assert page.status_code == 200, page.text
    return next(item for item in page.json()["items"] if item["slug"] == slug)


async def test_member_tags_filter_rename_trash_and_restore(
    client: AsyncClient,
) -> None:
    """A discussion claims catalog tags, filters, and follows curation."""
    org_id, owner_h, member_h, _ = await _org_with_member(client, "pt-live")
    base = f"/orgs/{org_id}/posts"
    made = await client.post(
        base,
        json={
            "kind": "discussion",
            "body": "hello",
            "tags": ["Hoc bong", "Y te"],
        },
        headers=member_h,
    )
    assert made.status_code == 201, made.text
    post_id = made.json()["post_id"]
    assert made.json()["tags"] == [
        {"name": "Hoc bong", "slug": "hoc-bong"},
        {"name": "Y te", "slug": "y-te"},
    ]

    filtered = await client.get(f"{base}?tag=hoc-bong", headers=member_h)
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["post_id"] == post_id

    blank = await client.get(f"{base}?tag=!!!", headers=member_h)
    assert blank.json()["total"] == 0

    row = await _catalog_row(client, org_id, owner_h, "hoc-bong")
    assert row["post_count"] == 1
    assert row["activity_count"] == 0

    draft = await client.post(
        base,
        json={
            "kind": "discussion",
            "title": "Later",
            "status": "draft",
            "tags": ["Nhap"],
        },
        headers=member_h,
    )
    assert draft.status_code == 201, draft.text
    draft_row = await _catalog_row(client, org_id, owner_h, "nhap")
    assert draft_row["post_count"] == 0

    kept = await client.patch(
        f"{base}/{post_id}",
        json={"body": "still tagged"},
        headers=member_h,
    )
    assert kept.status_code == 200, kept.text
    assert _slugs(kept.json()) == ["hoc-bong", "y-te"]

    renamed = await client.patch(
        f"/orgs/{org_id}/tags/hoc-bong",
        json={"name": "HOC BONG"},
        headers=owner_h,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["slug"] == "hoc-bong"
    detail = await client.get(f"{base}/{post_id}", headers=member_h)
    assert detail.json()["tags"][0] == {"name": "HOC BONG", "slug": "hoc-bong"}

    too_many = await client.post(
        base,
        json={
            "kind": "discussion",
            "body": "nope",
            "tags": ["One", "Two", "Three", "Four"],
        },
        headers=member_h,
    )
    assert too_many.status_code == 422
    catalog = await client.get(f"/orgs/{org_id}/tags", headers=owner_h)
    assert "four" not in {item["slug"] for item in catalog.json()["items"]}

    trashed = await client.delete(
        f"/orgs/{org_id}/tags/y-te", headers=owner_h
    )
    assert trashed.status_code == 200, trashed.text
    detached = await client.get(f"{base}/{post_id}", headers=member_h)
    assert _slugs(detached.json()) == ["hoc-bong"]

    blocked = await client.post(
        base,
        json={"kind": "discussion", "body": "reuse", "tags": ["Y te"]},
        headers=member_h,
    )
    assert blocked.status_code == 410
    assert blocked.json()["code"] == "TAG_DELETED"

    restored = await client.post(
        f"/orgs/{org_id}/tags/y-te/restore", headers=owner_h
    )
    assert restored.status_code == 200, restored.text
    back = await client.get(f"{base}/{post_id}", headers=member_h)
    assert _slugs(back.json()) == ["hoc-bong", "y-te"]


async def test_restore_skips_a_post_already_at_the_cap(
    client: AsyncClient,
) -> None:
    """A post filled with other tags while one was trashed stays full."""
    org_id, owner_h, member_h, _ = await _org_with_member(client, "pt-cap")
    base = f"/orgs/{org_id}/posts"
    made = await client.post(
        base,
        json={"kind": "discussion", "body": "cap", "tags": ["A", "B", "C"]},
        headers=member_h,
    )
    assert made.status_code == 201, made.text
    post_id = made.json()["post_id"]
    trashed = await client.delete(f"/orgs/{org_id}/tags/a", headers=owner_h)
    assert trashed.status_code == 200, trashed.text
    updated = await client.patch(
        f"{base}/{post_id}",
        json={"body": "cap", "tags": ["B", "C", "D"]},
        headers=member_h,
    )
    assert updated.status_code == 200, updated.text
    assert _slugs(updated.json()) == ["b", "c", "d"]
    restored = await client.post(
        f"/orgs/{org_id}/tags/a/restore", headers=owner_h
    )
    assert restored.status_code == 200, restored.text
    detail = await client.get(f"{base}/{post_id}", headers=member_h)
    assert _slugs(detail.json()) == ["b", "c", "d"]


async def test_publishing_a_revision_adopts_its_tags(
    client: AsyncClient,
) -> None:
    """The live post takes the revision's tags; the draft edges go away."""
    org_id, owner_h, member_h, _ = await _org_with_member(client, "pt-rev")
    base = f"/orgs/{org_id}/posts"
    made = await client.post(
        base,
        json={"kind": "discussion", "body": "live", "tags": ["Old"]},
        headers=member_h,
    )
    assert made.status_code == 201, made.text
    post_id = made.json()["post_id"]
    opened = await client.post(
        f"{base}/{post_id}/revisions", headers=member_h
    )
    assert opened.status_code == 200, opened.text
    revision_id = opened.json()["post_id"]
    assert _slugs(opened.json()) == ["old"]
    edited = await client.patch(
        f"{base}/{revision_id}",
        json={"body": "revised", "tags": ["Moi"]},
        headers=member_h,
    )
    assert edited.status_code == 200, edited.text
    published = await client.post(
        f"{base}/{revision_id}/publish", headers=member_h
    )
    assert published.status_code == 200, published.text
    assert published.json()["post_id"] == post_id
    assert published.json()["tags"] == [{"name": "Moi", "slug": "moi"}]
    parent = await client.get(f"{base}/{post_id}", headers=owner_h)
    assert _slugs(parent.json()) == ["moi"]
    gone = await client.get(f"{base}/{revision_id}", headers=member_h)
    assert gone.status_code == 404
