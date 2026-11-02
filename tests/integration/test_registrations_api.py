import uuid

from sqlalchemy import select

from src.app import app
from src.models.activities import ActivitySlot, Registration, RegistrationStatusHistory
from tests.activity_helpers import (
    Bearer,
    add_shift,
    at,
    first_error,
    make_org,
    published,
    sign_up,
    user,
)
from tests.conftest import ApiContext


def test_open_activity_approves_right_away(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))

    result = sign_up(api, volunteer, activity["id"], note="Toi co xe may")
    detail = api.client.get(f"/activities/{activity['id']}", headers=volunteer).json()
    mine = api.client.get("/registrations/mine", headers=volunteer).json()

    assert uuid.UUID(result["id"]).version == 7
    assert result["status"] == "approved"
    assert detail["seats_taken"] == 1
    assert detail["viewer"]["registrations"][0]["id"] == result["id"]
    assert mine[0]["activity_title"] == activity["title"]
    assert mine[0]["note"] == "Toi co xe may"
    assert mine[0]["can_cancel"] is True


def test_anyone_can_register_without_joining_the_organization(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    stranger, _ = user(api, bearer, "stranger")
    slug = make_org(api, owner)
    activity = published(api, owner, slug)

    sign_up(api, stranger, activity["id"])

    assert api.client.get(f"/organizations/{slug}").json()["member_count"] == 1


def test_registering_twice_is_a_conflict(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])

    again = api.client.post(
        f"/activities/{activity['id']}/registrations", headers=volunteer, json={}
    )

    assert again.status_code == 409
    assert again.json()["detail"] == "already_registered"


def test_full_activity_uses_the_waitlist_in_order(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    third, _ = user(api, bearer, "third")
    activity = published(api, owner, make_org(api, owner), max_participants=1)

    taken = sign_up(api, first, activity["id"])
    waiting = sign_up(api, second, activity["id"])
    behind = sign_up(api, third, activity["id"])

    assert taken["status"] == "approved"
    assert waiting["status"] == "waitlisted"
    assert waiting["waitlist_position"] == 1
    assert behind["waitlist_position"] == 2

    cancelled = api.client.delete(f"/registrations/{taken['id']}", headers=first)
    assert cancelled.status_code == 204

    detail = api.client.get(f"/activities/{activity['id']}", headers=second).json()
    assert detail["viewer"]["registrations"][0]["status"] == "approved"
    assert detail["seats_taken"] == 1
    assert detail["waitlist_count"] == 1
    third_view = api.client.get("/registrations/mine", headers=third).json()
    assert third_view[0]["waitlist_position"] == 1


def test_approval_flow_holds_the_seat(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    activity = published(
        api, owner, make_org(api, owner), max_participants=1, requires_approval=True
    )

    pending = sign_up(api, first, activity["id"])
    waiting = sign_up(api, second, activity["id"])

    assert pending["status"] == "pending"
    assert waiting["status"] == "waitlisted"

    path = f"/activities/{activity['id']}/registrations"
    listed = api.client.get(path, headers=owner, params={"status": "pending"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [pending["id"]]

    approved = api.client.post(
        f"/registrations/{pending['id']}/approve",
        headers=owner,
        json={"note": "Hen gap ban"},
    )
    assert approved.status_code == 204
    mine = api.client.get("/registrations/mine", headers=first).json()
    assert mine[0]["status"] == "approved"
    assert mine[0]["review_note"] == "Hen gap ban"

    again = api.client.post(
        f"/registrations/{pending['id']}/approve", headers=owner, json={}
    )
    assert again.json()["detail"] == "registration_not_pending"


def test_rejecting_frees_the_seat_for_the_next_person(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    activity = published(
        api, owner, make_org(api, owner), max_participants=1, requires_approval=True
    )
    taken = sign_up(api, first, activity["id"])
    sign_up(api, second, activity["id"])

    rejected = api.client.post(
        f"/registrations/{taken['id']}/reject",
        headers=owner,
        json={"note": "Da du nguoi"},
    )
    retry = api.client.post(
        f"/activities/{activity['id']}/registrations", headers=first, json={}
    )
    promoted = api.client.get("/registrations/mine", headers=second).json()

    assert rejected.status_code == 204
    assert retry.json()["detail"] == "registration_rejected"
    assert promoted[0]["status"] == "pending"


def test_cancelled_volunteer_can_register_again_at_the_back(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    activity = published(api, owner, make_org(api, owner), max_participants=1)
    taken = sign_up(api, first, activity["id"])
    api.client.delete(f"/registrations/{taken['id']}", headers=first)
    sign_up(api, second, activity["id"])

    back = sign_up(api, first, activity["id"])

    assert back["id"] == taken["id"]
    assert back["status"] == "waitlisted"


def test_shift_registration_counts_each_shift(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    activity = published(api, owner, make_org(api, owner))
    morning = add_shift(api, owner, activity["id"], capacity=1)
    evening = add_shift(api, owner, activity["id"], capacity=1, start=10.3, end=10.4)

    missing = api.client.post(
        f"/activities/{activity['id']}/registrations", headers=first, json={}
    )
    taken = sign_up(api, first, activity["id"], shift_id=morning["id"])
    waiting = sign_up(api, second, activity["id"], shift_id=morning["id"])
    other = sign_up(api, second, activity["id"], shift_id=evening["id"])
    detail = api.client.get(f"/activities/{activity['id']}").json()

    assert first_error(missing.json()) == ("shift_id", "shift_required")
    assert taken["status"] == "approved"
    assert waiting["status"] == "waitlisted"
    assert other["status"] == "approved"
    assert detail["capacity"] == 2
    assert detail["seats_taken"] == 2
    assert [shift["seats_taken"] for shift in detail["shifts"]] == [1, 1]
    with app.state.engine.connect() as connection:
        counted = connection.scalar(
            select(ActivitySlot.registered).where(
                ActivitySlot.slot_id == uuid.UUID(morning["id"])
            )
        )
    assert counted == 1


def test_overlapping_shifts_are_refused(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    first = add_shift(api, owner, activity["id"], start=10.1, end=10.3)
    second = add_shift(api, owner, activity["id"], start=10.2, end=10.4)
    sign_up(api, volunteer, activity["id"], shift_id=first["id"])

    response = api.client.post(
        f"/activities/{activity['id']}/registrations",
        headers=volunteer,
        json={"shift_id": second["id"]},
    )

    assert response.json()["detail"] == "shift_overlap"


def test_shift_with_registrations_cannot_be_deleted(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    shift = add_shift(api, owner, activity["id"])
    sign_up(api, volunteer, activity["id"], shift_id=shift["id"])

    response = api.client.delete(
        f"/activities/{activity['id']}/shifts/{shift['id']}", headers=owner
    )

    assert response.json()["detail"] == "shift_has_registrations"


def test_deadline_closes_registration(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), registration_deadline=at(1))
    path = f"/activities/{activity['id']}"
    api.client.patch(path, headers=owner, json={"registration_deadline": at(-1)})

    response = api.client.post(f"{path}/registrations", headers=volunteer, json={})

    assert response.json()["detail"] == "registration_closed"


def test_every_change_is_recorded_in_history(api: ApiContext, bearer: Bearer) -> None:
    owner, owner_id = user(api, bearer, "owner")
    volunteer, volunteer_id = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), requires_approval=True)
    registration = sign_up(api, volunteer, activity["id"])
    api.client.post(
        f"/registrations/{registration['id']}/approve", headers=owner, json={}
    )
    api.client.delete(f"/registrations/{registration['id']}", headers=volunteer)

    with app.state.engine.connect() as connection:
        rows = connection.execute(
            select(
                RegistrationStatusHistory.from_status,
                RegistrationStatusHistory.to_status,
                RegistrationStatusHistory.changed_by,
            )
            .where(
                RegistrationStatusHistory.registration_id
                == uuid.UUID(registration["id"])
            )
            .order_by(RegistrationStatusHistory.history_id)
        ).all()
        token = connection.scalar(
            select(Registration.checkin_token).where(
                Registration.registration_id == uuid.UUID(registration["id"])
            )
        )

    assert [tuple(map(str, row)) for row in rows] == [
        ("None", "pending", volunteer_id),
        ("pending", "approved", owner_id),
        ("approved", "cancelled", volunteer_id),
    ]
    assert token is not None
