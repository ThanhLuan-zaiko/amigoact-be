"""Integration tests: org-scoped tag curation endpoints over HTTP."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_activity_tags_db import (
    _BODY,
    _headers,
    _org,
    _publish,
)
from tests.integration.test_workspace_db import (
    _headers as _wrap_headers,
    _org_with_member,
    _token,
)


async def _activity(
    client: AsyncClient, org_id: str, headers: dict, tags: list[str]
) -> dict:
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": tags},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _get_activity(
    client: AsyncClient, aid: str, headers: dict
) -> dict:
    res = await client.get(f"/activities/{aid}", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def test_tag_crud_counts_and_feed_followup(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "ot.own@example.com", "0903000040")
    org_id = await _org(client, owner, "ot-crud")
    activity = await _activity(
        client,
        org_id,
        owner,
        ["M\u00f4i tr\u01b0\u1eddng", "Y t\u1ebf"],
    )
    aid = activity["id"]

    listed = await client.get(f"/orgs/{org_id}/tags", headers=owner)
    assert listed.status_code == 200
    page = listed.json()
    assert page["can_manage"] is True
    counts = {i["slug"]: i["activity_count"] for i in page["items"]}
    assert counts == {"moi-truong": 1, "y-te": 1}

    created = await client.post(
        f"/orgs/{org_id}/tags",
        json={"name": "Hi\u1ebfn m\u00e1u"},
        headers=owner,
    )
    assert created.status_code == 201, created.text
    assert created.json()["activity_count"] == 0

    dup = await client.post(
        f"/orgs/{org_id}/tags", json={"name": "hien mau"}, headers=owner
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "TAG_EXISTS"

    renamed = await client.patch(
        f"/orgs/{org_id}/tags/y-te",
        json={"name": "Ch\u0103m s\u00f3c s\u1ee9c kh\u1ecfe"},
        headers=owner,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["slug"] == "cham-soc-suc-khoe"
    detail = await _get_activity(client, aid, owner)
    assert detail["tags"] == [
        {"name": "M\u00f4i tr\u01b0\u1eddng", "slug": "moi-truong"},
        {
            "name": "Ch\u0103m s\u00f3c s\u1ee9c kh\u1ecfe",
            "slug": "cham-soc-suc-khoe",
        },
    ]

    await _publish(client, org_id, aid, owner)
    feed = await client.get("/activities?tag=cham-soc-suc-khoe")
    assert any(r["id"] == aid for r in feed.json())
    stale = await client.get("/activities?tag=y-te")
    assert all(r["id"] != aid for r in stale.json())

    merged = await client.post(
        f"/orgs/{org_id}/tags/moi-truong/merge",
        json={"into": "hien-mau"},
        headers=owner,
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["slug"] == "hien-mau"
    detail = await _get_activity(client, aid, owner)
    assert detail["tags"] == [
        {"name": "Hi\u1ebfn m\u00e1u", "slug": "hien-mau"},
        {
            "name": "Ch\u0103m s\u00f3c s\u1ee9c kh\u1ecfe",
            "slug": "cham-soc-suc-khoe",
        },
    ]

    deleted = await client.delete(
        f"/orgs/{org_id}/tags/hien-mau?hard=1", headers=owner
    )
    assert deleted.status_code == 204
    assert not deleted.content
    detail = await _get_activity(client, aid, owner)
    assert detail["tags"] == [
        {
            "name": "Ch\u0103m s\u00f3c s\u1ee9c kh\u1ecfe",
            "slug": "cham-soc-suc-khoe",
        }
    ]


async def test_trash_counts_and_restore_after_tag_delete(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "ot.trash@example.com", "0903000041")
    org_id = await _org(client, owner, "ot-trash")
    activity = await _activity(client, org_id, owner, ["Trash tag"])
    aid = activity["id"]

    trashed = await client.delete(
        f"/orgs/{org_id}/activities/{aid}", headers=owner
    )
    assert trashed.status_code == 200, trashed.text
    listed = await client.get(f"/orgs/{org_id}/tags", headers=owner)
    counts = {i["slug"]: i["activity_count"] for i in listed.json()["items"]}
    assert counts["trash-tag"] == 0

    gone = await client.delete(
        f"/orgs/{org_id}/tags/trash-tag?hard=1", headers=owner
    )
    assert gone.status_code == 204
    restored = await client.post(
        f"/orgs/{org_id}/activities/{aid}/restore", headers=owner
    )
    assert restored.status_code == 200, restored.text
    detail = await _get_activity(client, aid, owner)
    assert detail["tags"] == []


async def test_independent_catalogs_and_public_surface(
    client: AsyncClient,
) -> None:
    owner_a = await _headers(client, "ot.a@example.com", "0903000042")
    owner_b = await _headers(client, "ot.b@example.com", "0903000043")
    org_a = await _org(client, owner_a, "ot-ind-a")
    org_b = await _org(client, owner_b, "ot-ind-b")
    act_a = await _activity(client, org_a, owner_a, ["Tr\u1ed3ng r\u1eebng"])
    act_b = await _activity(client, org_b, owner_b, ["tr\u1ed3ng R\u1eeaNG"])

    assert act_a["tags"] == [
        {"name": "Tr\u1ed3ng r\u1eebng", "slug": "trong-rung"}
    ]
    assert act_b["tags"] == [
        {"name": "tr\u1ed3ng R\u1eeaNG", "slug": "trong-rung"}
    ]

    await _publish(client, org_a, act_a["id"], owner_a)
    await _publish(client, org_b, act_b["id"], owner_b)
    feed = await client.get("/activities?tag=trong-rung")
    assert {act_a["id"], act_b["id"]} <= {
        r["id"] for r in feed.json()
    }

    directory = await client.get("/tags?q=trong")
    rows = [
        r for r in directory.json() if r["slug"] == "trong-rung"
    ]
    assert len(rows) == 1
    assert set(rows[0].keys()) == {"name", "slug"}

    renamed = await client.patch(
        f"/orgs/{org_a}/tags/trong-rung",
        json={"name": "R\u1eebng xanh"},
        headers=owner_a,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["slug"] == "rung-xanh"
    other = await _get_activity(client, act_b["id"], owner_b)
    assert other["tags"] == [
        {"name": "tr\u1ed3ng R\u1eeaNG", "slug": "trong-rung"}
    ]


async def test_permissions_gate_curation(client: AsyncClient) -> None:
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "ot-perms"
    )
    await _activity(client, org_id, owner_h, ["Alpha"])

    listed = await client.get(f"/orgs/{org_id}/tags", headers=member_h)
    assert listed.status_code == 200
    assert listed.json()["can_manage"] is False

    for method, path, payload in (
        ("post", f"/orgs/{org_id}/tags", {"name": "Beta"}),
        ("patch", f"/orgs/{org_id}/tags/alpha", {"name": "Beta"}),
        (
            "post",
            f"/orgs/{org_id}/tags/alpha/merge",
            {"into": "beta"},
        ),
        ("delete", f"/orgs/{org_id}/tags/alpha", None),
    ):
        res = await client.request(
            method, path, json=payload, headers=member_h
        )
        assert res.status_code == 403, (method, path, res.text)
        assert res.json()["code"] == "FORBIDDEN"

    role = await client.post(
        f"/orgs/{org_id}/roles",
        json={"name": "Tag Ops", "permissions": ["tag:manage"]},
        headers=owner_h,
    )
    assert role.status_code == 201, role.text
    assigned = await client.patch(
        f"/orgs/{org_id}/members/{member_id}",
        json={"roles": ["Tag Ops"]},
        headers=owner_h,
    )
    assert assigned.status_code == 200, assigned.text

    created = await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Beta"}, headers=member_h
    )
    assert created.status_code == 201, created.text

    outsider = _wrap_headers(
        await _token(client, "ot-perms-out@x.com", "0912347004")
    )
    denied = await client.get(f"/orgs/{org_id}/tags", headers=outsider)
    assert denied.status_code == 403


async def test_inline_creation_feeds_the_catalog(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "ot.inl@example.com", "0903000044")
    org_id = await _org(client, owner, "ot-inline")
    await _activity(client, org_id, owner, ["S\u00e1ch c\u0169"])
    listed = await client.get(f"/orgs/{org_id}/tags", headers=owner)
    slugs = {i["slug"] for i in listed.json()["items"]}
    assert "sach-cu" in slugs


async def test_error_envelopes(client: AsyncClient) -> None:
    owner = await _headers(client, "ot.err@example.com", "0903000045")
    org_id = await _org(client, owner, "ot-errors")

    missing = await client.patch(
        f"/orgs/{org_id}/tags/ghost",
        json={"name": "X"},
        headers=owner,
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "TAG_NOT_FOUND"

    await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Alpha"}, headers=owner
    )
    self_merge = await client.post(
        f"/orgs/{org_id}/tags/alpha/merge",
        json={"into": "alpha"},
        headers=owner,
    )
    assert self_merge.status_code == 400
    assert self_merge.json()["code"] == "INVALID_TAG_MERGE"

    bad_name = await client.post(
        f"/orgs/{org_id}/tags", json={"name": "!!!"}, headers=owner
    )
    assert bad_name.status_code == 422
    assert bad_name.json()["code"] == "VALIDATION_ERROR"
