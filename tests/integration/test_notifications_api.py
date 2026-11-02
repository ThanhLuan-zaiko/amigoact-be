from typing import Any

from sqlalchemy import update

from src.app import app
from src.models.auth import User
from tests.activity_helpers import Bearer, Headers, make_org, published, sign_up, user
from tests.attendance_helpers import check_in, complete, open_session
from tests.conftest import ApiContext


def inbox(api: ApiContext, headers: Headers) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = api.client.get(
        "/notifications", headers=headers
    ).json()["items"]
    return items


def types(api: ApiContext, headers: Headers) -> list[str]:
    return [item["type"] for item in inbox(api, headers)]


def verify_email(api: ApiContext, name: str) -> None:
    with app.state.engine.begin() as connection:
        connection.execute(
            update(User)
            .where(User.email == api.email(name))
            .values(email_verified_at="2026-01-01T00:00:00Z")
        )


def test_review_tells_the_volunteer(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), requires_approval=True)
    registration = sign_up(api, volunteer, activity["id"])
    assert types(api, volunteer) == []

    api.client.post(
        f"/registrations/{registration['id']}/approve",
        headers=owner,
        json={"note": "Hen gap ban"},
    )

    item = inbox(api, volunteer)[0]
    assert item["type"] == "registration_approved"
    assert item["read"] is False
    assert item["data"]["activity_id"] == activity["id"]
    assert item["data"]["activity_title"] == activity["title"]
    assert item["data"]["note"] == "Hen gap ban"


def test_rejection_and_promotion_tell_the_right_people(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    activity = published(
        api, owner, make_org(api, owner), requires_approval=True, max_participants=1
    )
    taken = sign_up(api, first, activity["id"])
    sign_up(api, second, activity["id"])

    api.client.post(f"/registrations/{taken['id']}/reject", headers=owner, json={})

    assert types(api, first) == ["registration_rejected"]
    promoted = inbox(api, second)[0]
    assert promoted["type"] == "registration_promoted"
    assert promoted["data"]["status"] == "pending"


def test_cancelling_tells_each_person_once(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])

    api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)

    assert types(api, volunteer) == ["activity_cancelled"]


def test_membership_decision_tells_the_applicant(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    accepted, accepted_id = user(api, bearer, "accepted")
    refused, refused_id = user(api, bearer, "refused")
    slug = make_org(api, owner)
    for headers in (accepted, refused):
        api.client.post(f"/organizations/{slug}/join", headers=headers, json={})

    api.client.post(
        f"/organizations/{slug}/applications/{accepted_id}/approve", headers=owner
    )
    api.client.post(
        f"/organizations/{slug}/applications/{refused_id}/reject", headers=owner
    )

    item = inbox(api, accepted)[0]
    assert item["type"] == "membership_approved"
    assert item["data"]["organization_slug"] == slug
    assert types(api, refused) == ["membership_rejected"]


def test_hours_tell_the_volunteer(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="4.5")
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, token=session["qr_token"])

    complete(api, owner, activity["id"])

    item = inbox(api, volunteer)[0]
    assert item["type"] == "hours_awarded"
    assert item["data"]["hours"] == 4.5


def test_appeal_decisions_tell_the_volunteer(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="1")
    registration = sign_up(api, volunteer, activity["id"])
    complete(api, owner, activity["id"])
    api.client.post(
        f"/registrations/{registration['id']}/appeals",
        headers=volunteer,
        json={"reason": "Toi co mat hom do"},
    )
    appeal = api.client.get(
        f"/activities/{activity['id']}/appeals", headers=owner
    ).json()[0]

    api.client.post(f"/appeals/{appeal['id']}/reject", headers=owner)

    assert types(api, volunteer) == ["appeal_rejected"]


def test_read_state_and_unread_count(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    slug = make_org(api, owner)
    for _ in range(2):
        activity = published(api, owner, slug)
        sign_up(api, volunteer, activity["id"])
        api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)
    count_path = "/notifications/unread-count"

    assert api.client.get(count_path, headers=volunteer).json() == {"count": 2}
    newest = inbox(api, volunteer)[0]
    read = api.client.post(f"/notifications/{newest['id']}/read", headers=volunteer)
    again = api.client.post(f"/notifications/{newest['id']}/read", headers=volunteer)

    assert read.status_code == 204
    assert again.status_code == 204
    assert api.client.get(count_path, headers=volunteer).json() == {"count": 1}
    unread = api.client.get(
        "/notifications", headers=volunteer, params={"unread_only": True}
    ).json()
    assert len(unread["items"]) == 1
    assert unread["unread_count"] == 1

    everything = api.client.post("/notifications/read-all", headers=volunteer)

    assert everything.status_code == 204
    assert api.client.get(count_path, headers=volunteer).json() == {"count": 0}


def test_notifications_page(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    slug = make_org(api, owner)
    for _ in range(3):
        activity = published(api, owner, slug)
        sign_up(api, volunteer, activity["id"])
        api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)

    page = api.client.get(
        "/notifications", headers=volunteer, params={"limit": 2}
    ).json()

    assert len(page["items"]) == 2
    assert page["next_offset"] == 2
    assert page["unread_count"] == 3


def test_preferences_round_trip(api: ApiContext, bearer: Bearer) -> None:
    volunteer, _ = user(api, bearer, "volunteer")
    path = "/notifications/preferences"

    assert api.client.get(path, headers=volunteer).json() == {
        "inapp": True,
        "email": False,
        "muted_types": [],
    }
    saved = api.client.put(
        path,
        headers=volunteer,
        json={
            "inapp": True,
            "email": True,
            "muted_types": ["hours_awarded", "hours_awarded"],
        },
    )

    assert saved.json() == {
        "inapp": True,
        "email": True,
        "muted_types": ["hours_awarded"],
    }


def test_muted_type_creates_nothing(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    api.client.put(
        "/notifications/preferences",
        headers=volunteer,
        json={"muted_types": ["activity_cancelled"]},
    )

    api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)

    assert types(api, volunteer) == []


def test_email_goes_out_when_turned_on(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    verify_email(api, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    api.client.put(
        "/notifications/preferences", headers=volunteer, json={"email": True}
    )
    api.mailer.sent.clear()

    api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)

    assert len(api.mailer.sent) == 1
    to, subject, _ = api.mailer.sent[0]
    assert to == api.email("volunteer")
    assert activity["title"] in subject


def test_in_app_can_be_off_while_email_stays_on(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    verify_email(api, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    api.client.put(
        "/notifications/preferences",
        headers=volunteer,
        json={"inapp": False, "email": True},
    )
    api.mailer.sent.clear()

    api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)

    assert types(api, volunteer) == []
    assert len(api.mailer.sent) == 1
