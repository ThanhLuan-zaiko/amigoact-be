"""The live bell reaches only the people the notification belongs to."""

from sqlalchemy import update

from src.app import app
from src.models.notifications import Notification
from tests.activity_helpers import Bearer, make_org, user
from tests.chat_helpers import ticket
from tests.conftest import ApiContext
from tests.notification_helpers import apply, heard_nothing


def test_members_and_strangers_do_not_hear_applications(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    stranger, _ = user(api, bearer, "stranger")
    applicant, _ = user(api, bearer, "applicant")
    slug = make_org(api, owner)
    apply(api, slug, member, None)
    api.client.post(
        f"/organizations/{slug}/applications/{member_id}/approve", headers=owner
    )

    with (
        api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, member)}") as one,
        api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, stranger)}") as two,
        api.client.websocket_connect(
            f"/ws/chat?ticket={ticket(api, applicant)}"
        ) as three,
    ):
        apply(api, slug, applicant, "Ly do rieng tu")
        assert heard_nothing(one)
        assert heard_nothing(two)
        assert heard_nothing(three)


def test_refused_application_rings_nothing(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    applicant, _ = user(api, bearer, "applicant")
    slug = make_org(api, owner)
    apply(api, slug, applicant, None)

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, owner)}") as ws:
        again = apply(api, slug, applicant, "Lan nua")
        assert heard_nothing(ws)

    assert again.json()["detail"] == "already_applied"
    count = api.client.get("/notifications/unread-count", headers=owner).json()
    assert count == {"count": 1}


def test_muted_type_stays_silent(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    applicant, _ = user(api, bearer, "applicant")
    slug = make_org(api, owner)
    api.client.put(
        "/notifications/preferences",
        headers=owner,
        json={"inapp": True, "email": False, "muted_types": ["membership_requested"]},
    )

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, owner)}") as ws:
        apply(api, slug, applicant, None)
        assert heard_nothing(ws)


def test_withdrawal_leaves_other_notices_alone(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    leaving, leaving_id = user(api, bearer, "leaving")
    staying, staying_id = user(api, bearer, "staying")
    slug = make_org(api, owner)
    other_slug = make_org(api, owner)
    apply(api, slug, leaving, None)
    apply(api, other_slug, leaving, None)
    apply(api, slug, staying, None)

    api.client.delete(f"/organizations/{slug}/membership", headers=leaving)

    items = api.client.get("/notifications", headers=owner).json()["items"]
    left = {(i["data"]["organization_slug"], i["data"]["applicant_id"]) for i in items}
    assert left == {(other_slug, leaving_id), (slug, staying_id)}


def test_withdrawal_removes_notices_saved_before_organization_id(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    applicant, _ = user(api, bearer, "applicant")
    slug = make_org(api, owner)
    apply(api, slug, applicant, None)
    with app.state.engine.begin() as connection:
        connection.execute(
            update(Notification)
            .where(Notification.type == "membership_requested")
            .where(Notification.data_json["organization_slug"].astext == slug)
            .values(data_json=Notification.data_json.op("-")("organization_id"))
        )

    api.client.delete(f"/organizations/{slug}/membership", headers=applicant)

    count = api.client.get("/notifications/unread-count", headers=owner).json()
    assert count == {"count": 0}


def test_leaving_as_a_member_keeps_old_notices(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = make_org(api, owner)
    apply(api, slug, member, None)
    api.client.post(
        f"/organizations/{slug}/applications/{member_id}/approve", headers=owner
    )

    api.client.delete(f"/organizations/{slug}/membership", headers=member)

    # The request stays in the inbox; leaving adds its own notice.
    items = api.client.get("/notifications", headers=owner).json()["items"]
    assert [item["type"] for item in items] == ["member_left", "membership_requested"]
