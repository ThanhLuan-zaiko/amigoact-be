from typing import Any

from tests.activity_helpers import Bearer, make_org, user
from tests.chat_helpers import ticket
from tests.conftest import ApiContext
from tests.notification_helpers import apply, heard_nothing, make_admin, next_frame


def inbox(api: ApiContext, headers: dict[str, str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = api.client.get(
        "/notifications", headers=headers
    ).json()["items"]
    return items


def test_application_rings_the_owner_at_once(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    applicant, applicant_id = user(api, bearer, "applicant")
    slug = make_org(api, owner)

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, owner)}") as ws:
        response = apply(api, slug, applicant, "Toi muon giup do")
        frame = next_frame(ws)

    assert response.status_code == 200, response.text
    assert frame["type"] == "notification.created"
    pushed = frame["notification"]
    assert pushed["type"] == "membership_requested"
    assert pushed["read"] is False
    assert pushed["data"]["organization_slug"] == slug
    assert pushed["data"]["applicant_id"] == applicant_id
    assert pushed["data"]["message"] == "Toi muon giup do"

    # The pushed item is the same one the inbox lists.
    saved = inbox(api, owner)[0]
    assert saved["id"] == pushed["id"]
    assert saved["data"] == pushed["data"]
    count = api.client.get("/notifications/unread-count", headers=owner).json()
    assert count == {"count": 1}


def test_every_admin_hears_about_the_application(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    admin, admin_id = user(api, bearer, "admin")
    applicant, _ = user(api, bearer, "applicant")
    slug = make_org(api, owner)
    make_admin(api, owner, slug, admin, admin_id)

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, admin)}") as ws:
        apply(api, slug, applicant, None)
        frame = next_frame(ws)

    assert frame["notification"]["type"] == "membership_requested"
    assert frame["notification"]["data"]["message"] is None
    # The admin's own application rang the owner earlier, so there are two.
    owner_items = inbox(api, owner)
    assert [item["type"] for item in owner_items] == ["membership_requested"] * 2
    assert owner_items[0]["data"] == frame["notification"]["data"]


def test_open_organization_needs_no_review(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    joiner, _ = user(api, bearer, "joiner")
    slug = make_org(api, owner)
    api.client.patch(
        f"/organizations/{slug}", headers=owner, json={"join_policy": "open"}
    )

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, owner)}") as ws:
        apply(api, slug, joiner, "Xin chao")
        assert heard_nothing(ws)

    assert inbox(api, owner) == []


def test_reading_clears_the_bell_in_other_tabs(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    applicant, _ = user(api, bearer, "applicant")
    slug = make_org(api, owner)
    apply(api, slug, applicant, None)
    item_id = inbox(api, owner)[0]["id"]

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, owner)}") as ws:
        api.client.post(f"/notifications/{item_id}/read", headers=owner)
        one = next_frame(ws)
        api.client.post("/notifications/read-all", headers=owner)
        every = next_frame(ws)

    assert one == {"type": "notification.read", "id": item_id}
    assert every == {"type": "notification.read_all"}


def test_withdrawal_takes_the_request_back_at_once(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    applicant, _ = user(api, bearer, "applicant")
    slug = make_org(api, owner)
    apply(api, slug, applicant, "Xin vao")
    pending = inbox(api, owner)[0]

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, owner)}") as ws:
        withdrawn = api.client.delete(
            f"/organizations/{slug}/membership", headers=applicant
        )
        frame = next_frame(ws)

    assert withdrawn.status_code == 204
    assert frame["type"] == "notification.deleted"
    assert frame["notification"]["id"] == pending["id"]
    assert frame["notification"]["read"] is False
    assert frame["notification"]["data"]["organization_slug"] == slug
    assert inbox(api, owner) == []
    count = api.client.get("/notifications/unread-count", headers=owner).json()
    assert count == {"count": 0}


def test_decision_reaches_the_applicant_at_once(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    accepted, accepted_id = user(api, bearer, "accepted")
    refused, refused_id = user(api, bearer, "refused")
    slug = make_org(api, owner)
    apply(api, slug, accepted, None)
    apply(api, slug, refused, None)
    base = f"/organizations/{slug}/applications"

    with (
        api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, accepted)}") as a,
        api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, refused)}") as r,
    ):
        api.client.post(f"{base}/{accepted_id}/approve", headers=owner)
        approved = next_frame(a)
        api.client.post(f"{base}/{refused_id}/reject", headers=owner)
        rejected = next_frame(r)

    assert approved["notification"]["type"] == "membership_approved"
    assert approved["notification"]["data"]["organization_slug"] == slug
    assert rejected["notification"]["type"] == "membership_rejected"
    assert rejected["notification"]["data"]["organization_slug"] == slug
