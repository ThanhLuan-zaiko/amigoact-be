"""Regression tests: membership application flow over the real HTTP stack."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "phone": phone, "password": PASSWORD, "full_name": "Reg User"},
    )
    assert response.status_code == 201, response.text
    logged = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_review_org_apply_then_approve(client: AsyncClient) -> None:
    """Apply needs the form answers, lands applied, and approval makes it active."""
    owner_headers = _headers(await _token(client, "apown@example.com", "0912347201"))
    created = await client.post(
        "/orgs",
        json={
            "name": "Apply Club",
            "slug": "apply-club",
            "description": "",
            "kind": "club",
            "join_policy": "review",
        },
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]

    form = await client.put(
        f"/orgs/{org_id}/membership-form",
        json={"questions": [{"label": "Why?", "field_type": "textarea", "required": True}]},
        headers=owner_headers,
    )
    assert form.status_code == 200, form.text
    question_id = form.json()["questions"][0]["question_id"]

    applicant_headers = _headers(await _token(client, "apapp@example.com", "0912347202"))
    missing = await client.post(
        f"/orgs/{org_id}/members/apply", json={"answers": {}}, headers=applicant_headers
    )
    assert (missing.status_code, missing.json()["code"]) == (400, "ANSWER_REQUIRED")

    sent = await client.post(
        f"/orgs/{org_id}/members/apply",
        json={"answers": {question_id: "Helping kids"}},
        headers=applicant_headers,
    )
    assert sent.status_code == 201, sent.text
    assert sent.headers["location"] == f"/orgs/{org_id}/members/{sent.json()['user_id']}"
    user_id = sent.json()["user_id"]
    assert sent.json()["status"] == "applied"

    again = await client.post(
        f"/orgs/{org_id}/members/apply",
        json={"answers": {question_id: "Helping kids"}},
        headers=applicant_headers,
    )
    assert (again.status_code, again.json()["code"]) == (409, "ALREADY_APPLIED")

    read = await client.get(f"/orgs/{org_id}/members/{user_id}/application", headers=owner_headers)
    assert read.status_code == 200, read.text
    assert read.json()["answers"] == [
        {"question_id": question_id, "label": "Why?", "answer": "Helping kids"}
    ]

    approved = await client.post(f"/orgs/{org_id}/members/{user_id}/approve", headers=owner_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"

    mine = await client.get("/orgs/memberships/mine", headers=applicant_headers)
    assert mine.status_code == 200
    assert any(
        item["org_id"] == org_id and item["status"] == "active"
        for item in mine.json()["items"]
    )


async def test_invite_org_refuses_applications(client: AsyncClient) -> None:
    """Invite-only orgs keep answering apply with a 403 contract code."""
    owner_headers = _headers(await _token(client, "aiown@example.com", "0912347203"))
    created = await client.post(
        "/orgs",
        json={"name": "Invite Club", "slug": "invite-club", "description": "", "kind": "club"},
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]

    applicant_headers = _headers(await _token(client, "aiapp@example.com", "0912347204"))
    refused = await client.post(
        f"/orgs/{org_id}/members/apply", json={"answers": {}}, headers=applicant_headers
    )
    assert (refused.status_code, refused.json()["code"]) == (
        403,
        "NOT_ACCEPTING_APPLICATIONS",
    )
