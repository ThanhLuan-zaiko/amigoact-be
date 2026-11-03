from collections.abc import Callable

from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]


def test_verifying_the_email_unlocks_creating(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register(verified=False)["tokens"]["access_token"])
    payload = {**ORG_FIELDS, "name": f"CLB {api.tag}"}
    blocked = api.client.post("/organizations", headers=headers, json=payload)
    assert blocked.status_code == 403

    verified = api.client.post(
        "/auth/email/verify", json={"token": api.mailer.last_token()}
    )
    assert verified.status_code == 204

    response = api.client.post("/organizations", headers=headers, json=payload)
    assert response.status_code == 201


def test_unverified_user_can_still_join_and_browse(
    api: ApiContext, bearer: Bearer
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    member = bearer(api.register("member", verified=False)["tokens"]["access_token"])
    slug = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "join_policy": "open"},
    ).json()["slug"]

    joined = api.client.post(f"/organizations/{slug}/join", headers=member, json={})

    assert joined.status_code == 200, joined.text
    assert api.client.get("/organizations/mine", headers=member).status_code == 200
