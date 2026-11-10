import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from tests.activity_helpers import (
    Bearer,
    add_shift,
    at,
    draft,
    first_error,
    make_org,
    published,
    sign_up,
    user,
)
from tests.conftest import ApiContext


def test_last_seat_cannot_be_taken_twice(api: ApiContext, bearer: Bearer) -> None:
    # Regression guard: without the row lock, parallel requests overfill the activity.
    owner, _ = user(api, bearer, "owner")
    activity = published(api, owner, make_org(api, owner), max_participants=1)
    volunteers = [user(api, bearer, f"v{index}")[0] for index in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(lambda headers: sign_up(api, headers, activity["id"]), volunteers)
        )
    statuses = sorted(result["status"] for result in results)
    assert statuses == ["approved", *["waitlisted"] * 5]
    detail = api.client.get(f"/activities/{activity['id']}").json()
    assert detail["seats_taken"] == 1
    assert detail["waitlist_count"] == 5


def test_one_person_cannot_register_twice_in_parallel(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    path = f"/activities/{activity['id']}/registrations"
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(
            pool.map(
                lambda _: api.client.post(path, headers=volunteer, json={}).status_code,
                range(4),
            )
        )
    assert sorted(codes) == [201, 409, 409, 409]


def test_registration_list_never_exposes_contact_or_token(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    response = api.client.get(
        f"/activities/{activity['id']}/registrations", headers=owner
    )
    assert api.email("volunteer") not in response.text
    assert "checkin_token" not in response.text


def test_outsider_and_volunteer_cannot_review(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), requires_approval=True)
    registration = sign_up(api, volunteer, activity["id"])
    listed = api.client.get(
        f"/activities/{activity['id']}/registrations", headers=volunteer
    )

    self_approve = api.client.post(
        f"/registrations/{registration['id']}/approve", headers=volunteer, json={}
    )
    assert listed.status_code == 403
    assert self_approve.status_code == 403


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("PATCH", ""),
        ("DELETE", ""),
        ("POST", "/publish"),
        ("POST", "/complete"),
        ("POST", "/cancel"),
    ],
)
def test_only_managers_change_an_activity(
    api: ApiContext, bearer: Bearer, method: str, suffix: str
) -> None:
    owner, _ = user(api, bearer, "owner")
    other, _ = user(api, bearer, "other")
    activity = draft(api, owner, make_org(api, owner))
    response = api.client.request(
        method,
        f"/activities/{activity['id']}{suffix}",
        headers=other,
        json={} if method == "PATCH" else None,
    )
    assert response.status_code == 403


def test_someone_else_cannot_cancel_my_registration(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    registration = sign_up(api, volunteer, activity["id"])
    response = api.client.delete(f"/registrations/{registration['id']}", headers=owner)
    assert response.status_code == 404
    assert response.json()["detail"] == "registration_not_found"


def test_draft_cannot_be_registered_for(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = draft(api, owner, make_org(api, owner))
    response = api.client.post(
        f"/activities/{activity['id']}/registrations", headers=volunteer, json={}
    )
    assert response.json()["detail"] == "activity_not_open"


def test_shift_of_another_activity_is_refused(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    slug = make_org(api, owner)
    first = published(api, owner, slug)
    second = published(api, owner, slug)
    add_shift(api, owner, first["id"])
    foreign = add_shift(api, owner, second["id"])
    response = api.client.post(
        f"/activities/{first['id']}/registrations",
        headers=volunteer,
        json={"shift_id": foreign["id"]},
    )
    assert response.json()["detail"] == "shift_not_found"


def test_capacity_cannot_drop_below_seats_taken(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    activity = published(api, owner, make_org(api, owner), max_participants=5)
    sign_up(api, first, activity["id"])
    sign_up(api, second, activity["id"])
    response = api.client.patch(
        f"/activities/{activity['id']}",
        headers=owner,
        json={"max_participants": 1},
    )

    assert first_error(response.json()) == (
        "max_participants",
        "capacity_below_registered",
    )


def test_raising_capacity_promotes_the_waitlist(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    activity = published(api, owner, make_org(api, owner), max_participants=1)
    sign_up(api, first, activity["id"])
    sign_up(api, second, activity["id"])
    api.client.patch(
        f"/activities/{activity['id']}",
        headers=owner,
        json={"max_participants": 2},
    )
    mine = api.client.get("/registrations/mine", headers=second).json()
    assert mine[0]["status"] == "approved"


def test_adding_a_shift_is_refused_after_whole_activity_signups(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    response = api.client.post(
        f"/activities/{activity['id']}/shifts",
        headers=owner,
        json={
            "title": "Ca",
            "start_at": at(10.1),
            "end_at": at(10.2),
            "capacity": 1,
        },
    )
    assert response.json()["detail"] == "activity_has_registrations"


@pytest.mark.parametrize(
    ("payload", "field", "code"),
    [
        ({"title": "ab"}, "title", "string_too_short"),
        ({"title": "..."}, "title", "title_invalid"),
        ({"title": "Mua he", "location": "a\nb"}, "location", "text_invalid"),
        (
            {"title": "Mua he", "start_at": "2030-01-01T08:00:00"},
            "start_at",
            "timezone_aware",
        ),
        (
            {"title": "Mua he", "start_at": "khong-phai-gio"},
            "start_at",
            "datetime_from_date_parsing",
        ),
        (
            {"title": "Mua he", "max_participants": 0},
            "max_participants",
            "greater_than_equal",
        ),
        (
            {"title": "Mua he", "hours_awarded": "-1"},
            "hours_awarded",
            "greater_than_equal",
        ),
        (
            {"title": "Mua he", "hours_awarded": "1001"},
            "hours_awarded",
            "less_than_equal",
        ),
        ({"title": "Mua he", "org_id": "x"}, "org_id", "extra_forbidden"),
        ({"title": "Mua he", "status": "published"}, "status", "extra_forbidden"),
        (
            {
                "title": "Mua he",
                "start_at": "2030-01-02T08:00:00Z",
                "end_at": "2030-01-01T08:00:00Z",
            },
            "end_at",
            "end_before_start",
        ),
        (
            {
                "title": "Mua he",
                "start_at": "2030-01-02T08:00:00Z",
                "end_at": "2030-01-02T10:00:00Z",
                "registration_deadline": "2030-01-03T08:00:00Z",
            },
            "registration_deadline",
            "deadline_after_start",
        ),
    ],
)
def test_create_reports_the_exact_field_and_code(
    api: ApiContext,
    bearer: Bearer,
    payload: dict[str, Any],
    field: str,
    code: str,
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    complete = {
        "description": "Mo ta",
        "city": "Ha Noi",
        "hours_awarded": "2",
        "location": "San",
        "start_at": at(10),
        "end_at": at(11),
    }
    response = api.client.post(
        f"/organizations/{slug}/activities",
        headers=owner,
        json={**complete, **payload},
    )
    assert response.status_code == 422
    assert first_error(response.json()) == (field, code)


def test_paths_reject_ids_that_are_not_uuid7(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    not_v7 = uuid.uuid4()
    assert api.client.get(f"/activities/{not_v7}").status_code == 422
    deleted = api.client.delete(f"/registrations/{not_v7}", headers=owner)
    assert deleted.status_code == 422
    assert first_error(deleted.json()) == ("registration_id", "uuid_invalid")


def test_search_rejects_control_characters(api: ApiContext) -> None:
    assert api.client.get("/activities", params={"q": "a\x00b"}).status_code == 422
    assert api.client.get("/activities", params={"city": "a\x00b"}).status_code == 422


def test_incomplete_activity_is_never_published(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: the form checks these fields, but the API must refuse them too.
    owner, _ = user(api, bearer, "owner")
    activity = draft(api, owner, make_org(api, owner))
    api.client.patch(
        f"/activities/{activity['id']}", headers=owner, json={"description": None}
    )
    response = api.client.post(f"/activities/{activity['id']}/publish", headers=owner)
    assert response.status_code == 422
    assert first_error(response.json()) == ("description", "required")
