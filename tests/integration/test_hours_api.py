from tests.activity_helpers import (
    Bearer,
    add_shift,
    first_error,
    make_org,
    published,
    sign_up,
    user,
)
from tests.attendance_helpers import check_in, complete, open_session, start_now
from tests.conftest import ApiContext

REASON = "Toi co mat nhung dien thoai het pin"


def test_completing_awards_hours_only_to_attendees(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    came, came_id = user(api, bearer, "came")
    absent, _ = user(api, bearer, "absent")
    slug = make_org(api, owner)
    activity = published(api, owner, slug, hours_awarded="4.5")
    sign_up(api, came, activity["id"])
    sign_up(api, absent, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, came, token=session["qr_token"])

    body = complete(api, owner, activity["id"])

    assert body["status"] == "completed"
    mine = api.client.get("/hours/mine", headers=came).json()
    assert mine["total"] == 4.5
    assert mine["entries"][0]["activity_title"] == activity["title"]
    assert mine["entries"][0]["source"] == "attendance"
    assert mine["by_term"][0]["hours"] == 4.5
    assert api.client.get("/hours/mine", headers=absent).json()["total"] == 0
    came_regs = api.client.get("/registrations/mine", headers=came).json()
    assert came_regs[0]["status"] == "attended"
    absent_regs = api.client.get("/registrations/mine", headers=absent).json()
    assert absent_regs[0]["status"] == "approved"
    report = api.client.get(f"/activities/{activity['id']}/hours", headers=owner).json()
    assert [(item["user_id"], item["hours"]) for item in report] == [(came_id, 4.5)]
    org = api.client.get(f"/organizations/{slug}").json()
    assert org["volunteer_hours"] == 4.5
    assert org["activity_count"] == 1


def test_shift_earns_its_own_length(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    shift = add_shift(api, owner, activity["id"], start=10.0, end=10.25)
    sign_up(api, volunteer, activity["id"], shift_id=shift["id"])
    session = open_session(api, owner, activity["id"], shift_id=shift["id"])
    check_in(api, volunteer, token=session["qr_token"])

    complete(api, owner, activity["id"])

    assert api.client.get("/hours/mine", headers=volunteer).json()["total"] == 6


def test_completion_waits_for_typed_codes_to_be_reviewed(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="1")
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, code=session["manual_code"])
    start_now(activity["id"])

    response = api.client.post(f"/activities/{activity['id']}/complete", headers=owner)

    assert response.json()["detail"] == "attendance_pending_review"


def test_completion_needs_hours_when_someone_attended(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, token=session["qr_token"])
    start_now(activity["id"])

    response = api.client.post(f"/activities/{activity['id']}/complete", headers=owner)
    detail = api.client.get(f"/activities/{activity['id']}").json()

    assert response.json()["detail"] == "hours_required"
    assert detail["status"] == "published"


def test_adjustment_adds_a_ledger_row(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, volunteer_id = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="4")
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, token=session["qr_token"])
    complete(api, owner, activity["id"])
    path = f"/activities/{activity['id']}/hour-adjustments"

    adjusted = api.client.post(
        path,
        headers=owner,
        json={"user_id": volunteer_id, "delta_hours": "-1.5", "reason": "Ve som"},
    )
    too_much = api.client.post(
        path,
        headers=owner,
        json={"user_id": volunteer_id, "delta_hours": "-3", "reason": "Ve som hon"},
    )
    mine = api.client.get("/hours/mine", headers=volunteer).json()

    assert adjusted.status_code == 204
    assert too_much.json()["detail"] == "hours_would_go_negative"
    assert mine["total"] == 2.5
    assert {entry["source"] for entry in mine["entries"]} == {
        "attendance",
        "adjustment",
    }


def test_hour_rule_scales_and_caps(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    slug = make_org(api, owner)
    path = f"/organizations/{slug}/hour-rule"
    assert api.client.get(path, headers=owner).json() == {
        "multiplier": 1.0,
        "cap_hours": None,
    }
    saved = api.client.put(
        path, headers=owner, json={"multiplier": "2", "cap_hours": "10"}
    )
    assert saved.json() == {"multiplier": 2.0, "cap_hours": 10.0}
    first = published(api, owner, slug, hours_awarded="4")
    second = published(api, owner, slug, hours_awarded="4")
    for activity in (first, second):
        sign_up(api, volunteer, activity["id"])
        session = open_session(api, owner, activity["id"])
        check_in(api, volunteer, token=session["qr_token"])
        complete(api, owner, activity["id"])

    mine = api.client.get("/hours/mine", headers=volunteer).json()

    assert sorted(entry["hours"] for entry in mine["entries"]) == [2.0, 8.0]
    assert mine["total"] == 10


def test_appeal_after_completion_awards_the_hours(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="3")
    registration = sign_up(api, volunteer, activity["id"])
    complete(api, owner, activity["id"])

    created = api.client.post(
        f"/registrations/{registration['id']}/appeals",
        headers=volunteer,
        json={"reason": REASON},
    )
    twice = api.client.post(
        f"/registrations/{registration['id']}/appeals",
        headers=volunteer,
        json={"reason": REASON},
    )
    listed = api.client.get(
        f"/activities/{activity['id']}/appeals",
        headers=owner,
        params={"status": "pending"},
    ).json()

    assert created.status_code == 201
    assert twice.json()["detail"] == "appeal_already_pending"
    assert listed[0]["reason"] == REASON
    assert listed[0]["registrations"][0]["registration_id"] == registration["id"]

    approved = api.client.post(
        f"/appeals/{listed[0]['id']}/approve", headers=owner, json={}
    )
    again = api.client.post(
        f"/appeals/{listed[0]['id']}/approve", headers=owner, json={}
    )

    assert approved.status_code == 204
    assert again.json()["detail"] == "appeal_not_pending"
    assert api.client.get("/hours/mine", headers=volunteer).json()["total"] == 3
    mine = api.client.get("/registrations/mine", headers=volunteer).json()
    assert mine[0]["status"] == "attended"


def test_rejected_appeal_changes_nothing(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="3")
    registration = sign_up(api, volunteer, activity["id"])
    complete(api, owner, activity["id"])
    api.client.post(
        f"/registrations/{registration['id']}/appeals",
        headers=volunteer,
        json={"reason": REASON},
    )
    appeal = api.client.get(
        f"/activities/{activity['id']}/appeals", headers=owner
    ).json()[0]

    rejected = api.client.post(f"/appeals/{appeal['id']}/reject", headers=owner)

    assert rejected.status_code == 204
    assert api.client.get("/hours/mine", headers=volunteer).json()["total"] == 0
    listed = api.client.get(
        f"/activities/{activity['id']}/appeals",
        headers=owner,
        params={"status": "rejected"},
    ).json()
    assert listed[0]["registrations"] == []


def test_appeal_waits_until_the_activity_starts(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    registration = sign_up(api, volunteer, activity["id"])

    response = api.client.post(
        f"/registrations/{registration['id']}/appeals",
        headers=volunteer,
        json={"reason": REASON},
    )

    assert response.json()["detail"] == "appeal_not_allowed"


def test_appeal_with_several_shifts_needs_a_choice(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    first = add_shift(api, owner, activity["id"], start=10.0, end=10.1)
    second = add_shift(api, owner, activity["id"], start=10.2, end=10.3, title="Chieu")
    registration = sign_up(api, volunteer, activity["id"], shift_id=first["id"])
    chosen = sign_up(api, volunteer, activity["id"], shift_id=second["id"])
    start_now(activity["id"])
    api.client.post(
        f"/registrations/{registration['id']}/appeals",
        headers=volunteer,
        json={"reason": REASON},
    )
    appeal = api.client.get(
        f"/activities/{activity['id']}/appeals", headers=owner
    ).json()[0]
    path = f"/appeals/{appeal['id']}/approve"

    vague = api.client.post(path, headers=owner, json={})
    precise = api.client.post(
        path, headers=owner, json={"registration_id": chosen["id"]}
    )

    assert len(appeal["registrations"]) == 2
    assert first_error(vague.json()) == ("registration_id", "registration_required")
    assert precise.status_code == 204
