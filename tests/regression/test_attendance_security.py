import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

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


def test_only_approved_volunteers_can_check_in(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    stranger, _ = user(api, bearer, "stranger")
    waiting, _ = user(api, bearer, "waiting")
    pending, _ = user(api, bearer, "pending")
    activity = published(
        api, owner, make_org(api, owner), requires_approval=True, max_participants=1
    )
    sign_up(api, pending, activity["id"])
    sign_up(api, waiting, activity["id"])
    session = open_session(api, owner, activity["id"])

    for headers in (stranger, waiting, pending):
        response = check_in(api, headers, token=session["qr_token"])
        assert response.status_code == 403
        assert response.json()["detail"] == "not_registered_for_session"


def test_closed_session_refuses_check_in(api: ApiContext, bearer: Bearer) -> None:
    # Regression guard: an old photo of the QR must stop working.
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    api.client.post(f"/attendance-sessions/{session['id']}/close", headers=owner)

    by_qr = check_in(api, volunteer, token=session["qr_token"])
    by_code = check_in(api, volunteer, code=session["manual_code"])

    assert by_qr.json()["detail"] == "checkin_session_closed"
    assert by_code.json()["detail"] == "checkin_session_closed"


def test_unknown_codes_are_refused(api: ApiContext, bearer: Bearer) -> None:
    volunteer, _ = user(api, bearer, "volunteer")

    by_qr = check_in(api, volunteer, token="x" * 32)
    by_code = check_in(api, volunteer, code="ZZZZZZ")

    assert by_qr.json()["detail"] == "checkin_code_invalid"
    assert by_code.json()["detail"] == "checkin_code_invalid"


def test_check_in_requires_a_login(api: ApiContext) -> None:
    response = api.client.post("/attendance/check-in", json={"code": "ABC234"})

    assert response.status_code == 401


def test_session_secrets_stay_with_managers(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    registration = sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])

    calls = [
        ("GET", f"/activities/{activity['id']}/attendance-sessions", None),
        ("POST", f"/activities/{activity['id']}/attendance-sessions", {}),
        ("POST", f"/attendance-sessions/{session['id']}/close", None),
        ("GET", f"/attendance-sessions/{session['id']}/roster", None),
        (
            "POST",
            f"/attendance-sessions/{session['id']}/records",
            {"registration_id": registration["id"]},
        ),
        ("GET", f"/activities/{activity['id']}/hours", None),
        ("GET", f"/activities/{activity['id']}/appeals", None),
    ]
    for method, path, body in calls:
        response = api.client.request(method, path, headers=volunteer, json=body)
        assert response.status_code == 403, path
    public = api.client.get(f"/activities/{activity['id']}", headers=volunteer)
    assert session["qr_token"] not in public.text
    assert session["manual_code"] not in public.text


def test_volunteer_cannot_verify_their_own_typed_code(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, code=session["manual_code"])
    record_id = api.client.get(
        f"/attendance-sessions/{session['id']}/roster", headers=owner
    ).json()[0]["record_id"]

    verify = api.client.post(
        f"/attendance-records/{record_id}/verify", headers=volunteer
    )
    delete = api.client.delete(f"/attendance-records/{record_id}", headers=volunteer)

    assert verify.status_code == 403
    assert delete.status_code == 403


def test_someone_else_cannot_appeal_my_registration(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    other, _ = user(api, bearer, "other")
    activity = published(api, owner, make_org(api, owner), hours_awarded="1")
    registration = sign_up(api, volunteer, activity["id"])
    complete(api, owner, activity["id"])

    response = api.client.post(
        f"/registrations/{registration['id']}/appeals",
        headers=other,
        json={"reason": "Toi muon co gio"},
    )

    assert response.status_code == 404


def test_hours_are_never_awarded_twice(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner), hours_awarded="2")
    registration = sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, token=session["qr_token"])
    complete(api, owner, activity["id"])

    again = api.client.post(f"/activities/{activity['id']}/complete", headers=owner)
    appeal = api.client.post(
        f"/registrations/{registration['id']}/appeals",
        headers=volunteer,
        json={"reason": "Xin them gio cho toi"},
    )

    assert again.json()["detail"] == "activity_not_editable"
    assert appeal.json()["detail"] == "already_checked_in"
    assert api.client.get("/hours/mine", headers=volunteer).json()["total"] == 2


def test_parallel_scans_record_one_check_in(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(
            pool.map(
                lambda _: (
                    check_in(api, volunteer, token=session["qr_token"]).status_code
                ),
                range(4),
            )
        )

    assert sorted(codes) == [201, 409, 409, 409]


def test_cancelling_the_activity_closes_its_sessions(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])

    api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)
    response = check_in(api, volunteer, token=session["qr_token"])

    assert response.json()["detail"] == "checkin_session_closed"


@pytest.mark.parametrize(
    ("payload", "field", "code"),
    [
        ({}, "code", "checkin_input_required"),
        ({"code": "ABC"}, "code", "string_pattern_mismatch"),
        ({"token": "short"}, "token", "string_pattern_mismatch"),
        ({"code": "ABC234", "extra": "x"}, "extra", "extra_forbidden"),
    ],
)
def test_check_in_reports_the_exact_field_and_code(
    api: ApiContext,
    bearer: Bearer,
    payload: dict[str, Any],
    field: str,
    code: str,
) -> None:
    volunteer, _ = user(api, bearer, "volunteer")

    response = api.client.post("/attendance/check-in", headers=volunteer, json=payload)

    assert response.status_code == 422
    assert first_error(response.json()) == (field, code)


@pytest.mark.parametrize(
    ("method", "template"),
    [
        ("POST", "/attendance-sessions/{id}/close"),
        ("GET", "/attendance-sessions/{id}/roster"),
        ("POST", "/attendance-records/{id}/verify"),
        ("DELETE", "/attendance-records/{id}"),
        ("POST", "/appeals/{id}/reject"),
    ],
)
def test_paths_reject_ids_that_are_not_uuid7(
    api: ApiContext, bearer: Bearer, method: str, template: str
) -> None:
    owner, _ = user(api, bearer, "owner")

    response = api.client.request(
        method, template.format(id=uuid.uuid4()), headers=owner
    )

    assert response.status_code == 422
