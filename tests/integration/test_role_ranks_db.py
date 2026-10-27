"""Integration tests: role colour, seniority and the org member baseline."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import (
    _headers,
    _org_with_member,
    _token,
)


async def _add_member(
    client: AsyncClient, org_id: str, owner_h: dict, email: str, phone: str
) -> tuple[dict[str, str], str]:
    headers = _headers(await _token(client, email, phone))
    invited = await client.post(
        f"/orgs/{org_id}/members", json={"email": email}, headers=owner_h
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    return headers, invited.json()["user_id"]


async def _role(
    client: AsyncClient, org_id: str, headers: dict, name: str,
    permissions: list[str], color: str = "",
) -> dict:
    created = await client.post(
        f"/orgs/{org_id}/roles",
        json={"name": name, "permissions": permissions, "color": color},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _order(client: AsyncClient, org_id: str, headers: dict) -> list[str]:
    listed = await client.get(f"/orgs/{org_id}/roles", headers=headers)
    assert listed.status_code == 200, listed.text
    return [row["name"] for row in listed.json()["items"] if not row["is_system"]]


async def test_member_defaults_grant_and_revoke_baseline(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "rk-def")
    _, _ = await _add_member(
        client, org_id, owner_h, "rk-def-a@x.com", "0912347101"
    )
    invite = {"email": "rk-def-new@x.com"}
    await _token(client, "rk-def-new@x.com", "0912347102")

    # A plain member may not invite until the owner lifts the baseline.
    denied = await client.post(
        f"/orgs/{org_id}/members", json=invite, headers=member_h
    )
    assert denied.status_code == 403, denied.text

    put = await client.put(
        f"/orgs/{org_id}/roles/member-defaults",
        json={"permissions": ["member:invite"]},
        headers=owner_h,
    )
    assert put.status_code == 200, put.text
    assert put.json()["permissions"] == ["member:invite"]
    listed = await client.get(f"/orgs/{org_id}/roles", headers=member_h)
    assert listed.json()["member_defaults"] == ["member:invite"]
    assert "member:invite" in listed.json()["baseline_permissions"]
    members = await client.get(f"/orgs/{org_id}/members", headers=member_h)
    assert "member:invite" in members.json()["viewer_permissions"]

    allowed = await client.post(
        f"/orgs/{org_id}/members", json=invite, headers=member_h
    )
    assert allowed.status_code == 201, allowed.text

    # Moderation codes can never be baseline; only the owner may edit.
    bad = await client.put(
        f"/orgs/{org_id}/roles/member-defaults",
        json={"permissions": ["org:update"]},
        headers=owner_h,
    )
    assert (bad.status_code, bad.json()["code"]) == (400, "INVALID_ROLE")
    other = await client.put(
        f"/orgs/{org_id}/roles/member-defaults",
        json={"permissions": []},
        headers=member_h,
    )
    assert other.status_code == 403, other.text

    # An outsider never inherits the baseline.
    stranger_h = _headers(await _token(client, "rk-def-out@x.com", "0912347103"))
    out = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "rk-def-new@x.com"},
        headers=stranger_h,
    )
    assert out.status_code in (403, 404), out.text

    cleared = await client.put(
        f"/orgs/{org_id}/roles/member-defaults",
        json={"permissions": []},
        headers=owner_h,
    )
    assert cleared.json()["permissions"] == []


async def test_role_colour_and_order(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "rk-ord")
    first = await _role(client, org_id, owner_h, "Alpha", ["activity:view"], "red")
    second = await _role(client, org_id, owner_h, "Beta", ["activity:view"])
    assert first["color"] == "red" and second["color"] == ""
    # New roles sit below the existing ones.
    assert first["position"] > second["position"]
    assert await _order(client, org_id, owner_h) == ["Alpha", "Beta"]

    bad = await client.post(
        f"/orgs/{org_id}/roles",
        json={"name": "Neon", "permissions": ["activity:view"], "color": "pink"},
        headers=owner_h,
    )
    assert (bad.status_code, bad.json()["code"]) == (400, "INVALID_ROLE")

    recolour = await client.patch(
        f"/orgs/{org_id}/roles/{second['id']}",
        json={"color": "emerald"},
        headers=owner_h,
    )
    assert recolour.status_code == 200 and recolour.json()["color"] == "emerald"

    flipped = await client.put(
        f"/orgs/{org_id}/roles/order",
        json={"role_ids": [second["id"], first["id"]]},
        headers=owner_h,
    )
    assert flipped.status_code == 200, flipped.text
    assert [r["name"] for r in flipped.json()["items"] if not r["is_system"]] == [
        "Beta",
        "Alpha",
    ]
    partial = await client.put(
        f"/orgs/{org_id}/roles/order",
        json={"role_ids": [first["id"]]},
        headers=owner_h,
    )
    assert (partial.status_code, partial.json()["code"]) == (400, "INVALID_ROLE")
    denied = await client.put(
        f"/orgs/{org_id}/roles/order",
        json={"role_ids": [first["id"], second["id"]]},
        headers=member_h,
    )
    assert denied.status_code == 403, denied.text


async def test_role_hierarchy_limits_delegates(client: AsyncClient) -> None:
    org_id, owner_h, lead_h, lead_id = await _org_with_member(
        client, "rk-hier"
    )
    _, third_id = await _add_member(
        client, org_id, owner_h, "rk-hier-c@x.com", "0912347111"
    )
    lead = await _role(
        client, org_id, owner_h, "Lead", ["member:role-assign", "activity:view"]
    )
    junior = await _role(client, org_id, owner_h, "Junior", ["activity:view"])
    assigned = await client.patch(
        f"/orgs/{org_id}/members/{lead_id}",
        json={"roles": ["Lead"]},
        headers=owner_h,
    )
    assert assigned.status_code == 200, assigned.text
    await client.put(
        f"/orgs/{org_id}/roles/order",
        json={"role_ids": [lead["id"], junior["id"]]},
        headers=owner_h,
    )

    roster = await client.get(f"/orgs/{org_id}/members", headers=lead_h)
    assert isinstance(roster.json()["viewer_ceiling"], int)
    owner_roster = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    assert owner_roster.json()["viewer_ceiling"] is None

    # Lead outranks Junior: may edit it and hand it out.
    ok = await client.patch(
        f"/orgs/{org_id}/roles/{junior['id']}",
        json={"color": "amber"},
        headers=lead_h,
    )
    assert ok.status_code == 200, ok.text
    give = await client.patch(
        f"/orgs/{org_id}/members/{third_id}",
        json={"roles": ["Junior"]},
        headers=lead_h,
    )
    assert give.status_code == 200, give.text

    # Never their own rank or above.
    own = await client.patch(
        f"/orgs/{org_id}/roles/{lead['id']}",
        json={"color": "red"},
        headers=lead_h,
    )
    assert (own.status_code, own.json()["code"]) == (403, "ROLE_ABOVE_YOU")

    await client.put(
        f"/orgs/{org_id}/roles/order",
        json={"role_ids": [junior["id"], lead["id"]]},
        headers=owner_h,
    )
    above = await client.patch(
        f"/orgs/{org_id}/roles/{junior['id']}",
        json={"color": "red"},
        headers=lead_h,
    )
    assert (above.status_code, above.json()["code"]) == (403, "ROLE_ABOVE_YOU")
    revoke = await client.patch(
        f"/orgs/{org_id}/members/{third_id}",
        json={"roles": []},
        headers=lead_h,
    )
    assert (revoke.status_code, revoke.json()["code"]) == (403, "ROLE_ABOVE_YOU")
