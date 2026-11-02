from tests.activity_helpers import (
    Bearer,
    add_shift,
    make_org,
    published,
    sign_up,
    user,
)
from tests.attendance_helpers import attended_activity, check_in, complete, open_session
from tests.conftest import ApiContext


def test_issue_only_to_people_who_attended(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    came, came_id = user(api, bearer, "came")
    absent, _ = user(api, bearer, "absent")
    activity = published(api, owner, make_org(api, owner), hours_awarded="4.5")
    sign_up(api, came, activity["id"])
    sign_up(api, absent, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, came, token=session["qr_token"])
    complete(api, owner, activity["id"])
    path = f"/activities/{activity['id']}/certificates"

    before = api.client.get(path, headers=owner).json()
    issued = api.client.post(path, headers=owner)
    after = api.client.get(path, headers=owner).json()

    assert before == {"items": [], "missing_count": 1}
    assert issued.json() == {"issued": 1}
    assert after["missing_count"] == 0
    assert after["items"][0]["user_id"] == came_id
    assert after["items"][0]["hours"] == 4.5
    assert after["items"][0]["serial_no"].startswith("AMG-")
    mine = api.client.get("/certificates/mine", headers=came).json()
    assert mine[0]["activity_title"] == activity["title"]
    assert api.client.get("/certificates/mine", headers=absent).json() == []
    types = [
        item["type"]
        for item in api.client.get("/notifications", headers=came).json()["items"]
    ]
    assert "certificate_issued" in types


def test_issuing_again_adds_nothing(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = attended_activity(api, owner, volunteer)
    path = f"/activities/{activity['id']}/certificates"
    api.client.post(path, headers=owner)

    again = api.client.post(path, headers=owner)

    assert again.json() == {"issued": 0}
    assert len(api.client.get(path, headers=owner).json()["items"]) == 1


def test_several_shifts_earn_one_certificate(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    for start, end in ((10.0, 10.1), (10.2, 10.3)):
        shift = add_shift(api, owner, activity["id"], start=start, end=end)
        sign_up(api, volunteer, activity["id"], shift_id=shift["id"])
        session = open_session(api, owner, activity["id"], shift_id=shift["id"])
        check_in(api, volunteer, token=session["qr_token"])
    complete(api, owner, activity["id"])

    issued = api.client.post(
        f"/activities/{activity['id']}/certificates", headers=owner
    )

    assert issued.json() == {"issued": 1}


def test_issue_waits_until_the_activity_ends(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    activity = published(api, owner, make_org(api, owner))

    response = api.client.post(
        f"/activities/{activity['id']}/certificates", headers=owner
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "activity_not_completed"


def test_anyone_can_verify_by_serial(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = attended_activity(api, owner, volunteer)
    path = f"/activities/{activity['id']}/certificates"
    api.client.post(path, headers=owner)
    serial = api.client.get(path, headers=owner).json()["items"][0]["serial_no"]

    response = api.client.get(f"/certificates/verify/{serial.lower()}")

    assert response.status_code == 200
    body = response.json()
    assert body["serial_no"] == serial
    assert body["status"] == "issued"
    assert body["full_name"] == "Test User"
    assert body["hours"] == 4.5
    assert body["activity_title"] == activity["title"]
    assert body["revoked_at"] is None


def test_revoke_shows_in_verification_and_can_be_undone(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = attended_activity(api, owner, volunteer)
    path = f"/activities/{activity['id']}/certificates"
    api.client.post(path, headers=owner)
    item = api.client.get(path, headers=owner).json()["items"][0]
    verify = f"/certificates/verify/{item['serial_no']}"

    revoked = api.client.post(
        f"/certificates/{item['id']}/revoke",
        headers=owner,
        json={"reason": "Cap nham nguoi"},
    )
    twice = api.client.post(
        f"/certificates/{item['id']}/revoke",
        headers=owner,
        json={"reason": "Cap nham nguoi"},
    )
    public = api.client.get(verify).json()
    notice = api.client.get("/notifications", headers=volunteer).json()["items"][0]

    assert revoked.status_code == 204
    assert twice.json()["detail"] == "certificate_not_issued"
    assert public["status"] == "revoked"
    assert public["revoked_at"] is not None
    assert notice["type"] == "certificate_revoked"
    assert notice["data"]["reason"] == "Cap nham nguoi"

    restored = api.client.post(f"/certificates/{item['id']}/reinstate", headers=owner)

    assert restored.status_code == 204
    assert api.client.get(verify).json()["status"] == "issued"
    again = api.client.post(f"/certificates/{item['id']}/reinstate", headers=owner)
    assert again.json()["detail"] == "certificate_not_revoked"


def test_unknown_serial_returns_not_found(api: ApiContext) -> None:
    response = api.client.get("/certificates/verify/AMG-AAAA-AAAA-AAAA")

    assert response.status_code == 404
    assert response.json()["detail"] == "certificate_not_found"
