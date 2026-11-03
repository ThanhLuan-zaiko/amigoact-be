import uuid

import pytest
from sqlalchemy import select, update

from src.app import app
from src.models.auth import User
from src.models.notifications import Notification
from tests.activity_helpers import (
    Bearer,
    first_error,
    make_org,
    published,
    sign_up,
    user,
)
from tests.attendance_helpers import check_in, complete, open_session
from tests.conftest import ApiContext


def test_notifications_stay_private(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    other, _ = user(api, bearer, "other")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)
    item = api.client.get("/notifications", headers=volunteer).json()["items"][0]

    theirs = api.client.get("/notifications", headers=other).json()
    read = api.client.post(f"/notifications/{item['id']}/read", headers=other)

    assert theirs["items"] == []
    assert read.status_code == 404
    still = api.client.get("/notifications/unread-count", headers=volunteer)
    assert still.json() == {"count": 1}


def test_notifications_require_a_login(api: ApiContext) -> None:
    for path in (
        "/notifications",
        "/notifications/unread-count",
        "/notifications/preferences",
        "/certificates/mine",
    ):
        assert api.client.get(path).status_code == 401


def test_failed_action_leaves_no_notification_or_email(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: a notification belongs to the action's transaction.
    owner, _ = user(api, bearer, "owner")
    volunteer, volunteer_id = user(api, bearer, "volunteer")
    with app.state.engine.begin() as connection:
        connection.execute(
            update(User)
            .where(User.email == api.email("volunteer"))
            .values(email_verified_at="2026-01-01T00:00:00Z")
        )
    api.client.put(
        "/notifications/preferences", headers=volunteer, json={"email": True}
    )
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, token=session["qr_token"])
    api.mailer.sent.clear()
    from tests.attendance_helpers import start_now

    start_now(activity["id"])
    # No hours were set, so completing fails after attendance has been read.
    failed = api.client.post(f"/activities/{activity['id']}/complete", headers=owner)

    assert failed.json()["detail"] == "hours_required"
    assert api.mailer.sent == []
    with app.state.engine.connect() as connection:
        rows = connection.scalars(
            select(Notification.type).where(
                Notification.user_id == uuid.UUID(volunteer_id)
            )
        ).all()
    assert rows == []


def test_email_skips_an_unconfirmed_address(api: ApiContext, bearer: Bearer) -> None:
    # Regression guard: an unconfirmed address may belong to someone else.
    owner, _ = user(api, bearer, "owner")
    volunteer = bearer(
        api.register("volunteer", verified=False)["tokens"]["access_token"]
    )
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    api.client.put(
        "/notifications/preferences", headers=volunteer, json={"email": True}
    )
    api.mailer.sent.clear()

    api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)

    assert api.mailer.sent == []
    types = api.client.get("/notifications", headers=volunteer).json()["items"]
    assert [item["type"] for item in types] == ["activity_cancelled"]


def test_only_managers_handle_certificates(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="1")
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, token=session["qr_token"])
    complete(api, owner, activity["id"])
    path = f"/activities/{activity['id']}/certificates"

    assert api.client.post(path, headers=volunteer).status_code == 403
    assert api.client.get(path, headers=volunteer).status_code == 403
    api.client.post(path, headers=owner)
    item = api.client.get(path, headers=owner).json()["items"][0]
    revoke = api.client.post(
        f"/certificates/{item['id']}/revoke",
        headers=volunteer,
        json={"reason": "Toi muon thu hoi"},
    )
    reinstate = api.client.post(
        f"/certificates/{item['id']}/reinstate", headers=volunteer
    )
    assert revoke.status_code == 403
    assert reinstate.status_code == 403


def test_public_verification_exposes_no_contact_or_reason(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="1")
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, token=session["qr_token"])
    complete(api, owner, activity["id"])
    path = f"/activities/{activity['id']}/certificates"
    api.client.post(path, headers=owner)
    item = api.client.get(path, headers=owner).json()["items"][0]
    reason = "Ly do noi bo khong cong khai"
    api.client.post(
        f"/certificates/{item['id']}/revoke", headers=owner, json={"reason": reason}
    )

    response = api.client.get(f"/certificates/verify/{item['serial_no']}")

    assert api.email("volunteer") not in response.text
    assert reason not in response.text
    assert "user_id" not in response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/notifications/{id}/read"),
        ("POST", "/certificates/{id}/reinstate"),
    ],
)
def test_paths_reject_ids_that_are_not_uuid7(
    api: ApiContext, bearer: Bearer, method: str, path: str
) -> None:
    owner, _ = user(api, bearer, "owner")

    response = api.client.request(method, path.format(id=uuid.uuid4()), headers=owner)

    assert response.status_code == 422
    assert first_error(response.json())[1] == "uuid_invalid"


def test_bad_serial_is_rejected(api: ApiContext) -> None:
    assert api.client.get("/certificates/verify/a%00b%00c%00d").status_code == 422


def test_preferences_report_the_exact_field(api: ApiContext, bearer: Bearer) -> None:
    volunteer, _ = user(api, bearer, "volunteer")

    response = api.client.put(
        "/notifications/preferences",
        headers=volunteer,
        json={"sms": True},
    )

    assert response.status_code == 422
    assert first_error(response.json()) == ("sms", "extra_forbidden")
