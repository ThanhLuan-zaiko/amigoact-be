import uuid

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


def test_manager_creates_a_draft_hidden_from_others(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug, hours_awarded="2.50", requires_approval=True)
    assert uuid.UUID(activity["id"]).version == 7
    assert activity["status"] == "draft"
    assert activity["hours_awarded"] == 2.5
    assert activity["requires_approval"] is True
    assert activity["viewer"]["can_manage"] is True
    path = f"/activities/{activity['id']}"
    assert api.client.get(path).status_code == 404
    assert api.client.get(path, headers=owner).status_code == 200
    public = api.client.get("/activities", params={"q": api.tag}).json()
    assert public["items"] == []
    org_list = f"/organizations/{slug}/activities"
    assert api.client.get(org_list).json()["items"] == []
    assert len(api.client.get(org_list, headers=owner).json()["items"]) == 1


def test_non_manager_cannot_create(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    other, _ = user(api, bearer, "other")
    slug = make_org(api, owner)
    response = api.client.post(
        f"/organizations/{slug}/activities",
        headers=other,
        json={
            "title": "Mua he",
            "description": "Mo ta",
            "city": "Ha Noi",
            "location": "San",
            "hours_awarded": "2",
            "start_at": at(10),
            "end_at": at(11),
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "organization_forbidden"


def test_publish_lists_it_publicly(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = published(api, owner, slug, city="Ha Noi", max_participants=3)
    assert activity["status"] == "published"
    assert activity["published_at"] is not None
    assert activity["registration_open"] is True
    found = api.client.get("/activities", params={"q": api.tag}).json()["items"]
    assert [item["id"] for item in found] == [activity["id"]]
    assert found[0]["capacity"] == 3
    assert found[0]["seats_taken"] == 0
    assert found[0]["organization_slug"] == slug
    by_city = api.client.get("/activities", params={"q": api.tag, "city": "noi"})
    assert len(by_city.json()["items"]) == 1
    other_city = api.client.get("/activities", params={"q": api.tag, "city": "Hue"})
    assert other_city.json()["items"] == []


def test_publish_reports_what_is_missing(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug)
    # The create API insists on these fields, so they are cleared by an edit.
    cleared = {"location": None, "start_at": None, "end_at": None}
    api.client.patch(f"/activities/{activity['id']}", headers=owner, json=cleared)
    response = api.client.post(f"/activities/{activity['id']}/publish", headers=owner)
    assert response.status_code == 422
    fields = {item["loc"][-1]: item["type"] for item in response.json()["detail"]}
    assert fields == {
        "start_at": "required",
        "end_at": "required",
        "location": "required",
    }


def test_create_needs_every_field_the_form_asks_for(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    response = api.client.post(
        f"/organizations/{slug}/activities", headers=owner, json={"title": "Mua he"}
    )
    assert response.status_code == 422
    fields = {item["loc"][-1] for item in response.json()["detail"]}
    assert fields == {"description", "city", "start_at", "end_at", "hours_awarded"}


def test_remote_activity_needs_no_place_but_others_do(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    remote = draft(api, owner, slug, location=None, is_remote=True)
    assert remote["is_remote"] is True
    response = api.client.post(
        f"/organizations/{slug}/activities",
        headers=owner,
        json={
            "title": "Mua he",
            "description": "Mo ta",
            "city": "Ha Noi",
            "hours_awarded": "2",
            "start_at": at(10),
            "end_at": at(11),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "location"


def test_publish_needs_description_city_and_hours(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug)
    cleared = {"description": None, "city": None, "hours_awarded": None}
    api.client.patch(f"/activities/{activity['id']}", headers=owner, json=cleared)
    response = api.client.post(f"/activities/{activity['id']}/publish", headers=owner)
    assert response.status_code == 422
    fields = {item["loc"][-1]: item["type"] for item in response.json()["detail"]}
    assert fields == {
        "description": "required",
        "city": "required",
        "hours_awarded": "required",
    }
    stored = api.client.get(f"/activities/{activity['id']}", headers=owner)
    assert stored.json()["status"] == "draft"


def test_public_list_is_soonest_first_and_pages(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    later = published(api, owner, slug, start_at=at(20), end_at=at(21))
    sooner = published(api, owner, slug, start_at=at(5), end_at=at(6))
    first = api.client.get("/activities", params={"q": api.tag, "limit": 1}).json()
    second = api.client.get(
        "/activities",
        params={"q": api.tag, "limit": 1, "offset": first["next_offset"]},
    ).json()
    assert first["items"][0]["id"] == sooner["id"]
    assert second["items"][0]["id"] == later["id"]
    assert second["next_offset"] is None


def test_update_changes_only_sent_fields(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug, description="Cu", city="Hue")
    path = f"/activities/{activity['id']}"
    response = api.client.patch(
        path, headers=owner, json={"city": None, "requires_approval": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["city"] is None
    assert body["requires_approval"] is True
    assert body["description"] == "Cu"


def test_only_a_draft_can_be_deleted(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    plan = draft(api, owner, slug)
    live = published(api, owner, slug)
    removed = api.client.delete(f"/activities/{plan['id']}", headers=owner)
    refused = api.client.delete(f"/activities/{live['id']}", headers=owner)
    assert removed.status_code == 204
    assert api.client.get(f"/activities/{plan['id']}", headers=owner).status_code == 404
    assert refused.json()["detail"] == "activity_not_draft"


def test_cancel_closes_it_and_cancels_registrations(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    slug = make_org(api, owner)
    activity = published(api, owner, slug)
    path = f"/activities/{activity['id']}"
    sign_up(api, volunteer, activity["id"])
    body = api.client.post(f"{path}/cancel", headers=owner).json()
    mine = api.client.get("/registrations/mine", headers=volunteer).json()
    edit = api.client.patch(path, headers=owner, json={"city": "Hue"})
    assert body["status"] == "cancelled"
    assert body["seats_taken"] == 0
    assert body["registration_open"] is False
    assert mine[0]["status"] == "cancelled"
    assert edit.json()["detail"] == "activity_not_editable"


def test_complete_waits_for_the_start(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = published(api, owner, slug)
    response = api.client.post(f"/activities/{activity['id']}/complete", headers=owner)
    assert response.json()["detail"] == "activity_not_started"


def test_shift_lifecycle(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug)
    path = f"/activities/{activity['id']}"
    shift = add_shift(api, owner, activity["id"], capacity=4)
    add_shift(api, owner, activity["id"], capacity=6, start=10.3, end=10.4)
    detail = api.client.get(path, headers=owner).json()
    assert uuid.UUID(shift["id"]).version == 7
    assert detail["capacity"] == 10
    assert len(detail["shifts"]) == 2
    updated = api.client.put(
        f"{path}/shifts/{shift['id']}",
        headers=owner,
        json={
            "title": "Ca chieu",
            "start_at": at(10.1),
            "end_at": at(10.2),
            "capacity": 8,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Ca chieu"
    assert updated.json()["capacity"] == 8
    removed = api.client.delete(f"{path}/shifts/{shift['id']}", headers=owner)
    assert removed.status_code == 204
    assert len(api.client.get(path, headers=owner).json()["shifts"]) == 1


def test_shift_must_fit_inside_the_activity(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug)
    response = api.client.post(
        f"/activities/{activity['id']}/shifts",
        headers=owner,
        json={
            "title": "Ca",
            "start_at": at(9),
            "end_at": at(10.5),
            "capacity": 1,
        },
    )
    assert response.status_code == 422
    assert first_error(response.json()) == ("start_at", "shift_outside_activity")


def test_activity_time_cannot_exclude_a_shift(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug)
    add_shift(api, owner, activity["id"])
    response = api.client.patch(
        f"/activities/{activity['id']}",
        headers=owner,
        json={"start_at": at(10.5)},
    )

    assert first_error(response.json()) == (
        "start_at",
        "activity_time_excludes_shift",
    )


def test_unknown_activity_returns_not_found(api: ApiContext) -> None:
    response = api.client.get(f"/activities/{uuid.uuid7()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "activity_not_found"
