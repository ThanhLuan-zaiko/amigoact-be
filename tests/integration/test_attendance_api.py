from sqlalchemy import select

from src.app import app
from src.models.attendance import QrCode, QrScanLog
from tests.activity_helpers import (
    Bearer,
    add_shift,
    make_org,
    published,
    sign_up,
    user,
)
from tests.attendance_helpers import check_in, open_session
from tests.conftest import ApiContext


def test_manager_opens_a_session_with_both_codes(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    activity = published(api, owner, make_org(api, owner))

    session = open_session(api, owner, activity["id"], title="Sang", minutes=30)
    listed = api.client.get(
        f"/activities/{activity['id']}/attendance-sessions", headers=owner
    ).json()

    assert session["is_open"] is True
    assert len(session["manual_code"]) == 6
    assert len(session["qr_token"]) >= 32
    assert session["checked_in_count"] == 0
    assert [item["id"] for item in listed] == [session["id"]]


def test_session_without_shifts_does_not_become_a_shift(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: the hidden schedule must not make signups ask for a shift.
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))

    open_session(api, owner, activity["id"])
    detail = api.client.get(f"/activities/{activity['id']}").json()
    result = sign_up(api, volunteer, activity["id"])

    assert detail["shifts"] == []
    assert result["status"] == "approved"


def test_only_one_open_session_at_a_time(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    activity = published(api, owner, make_org(api, owner))
    session = open_session(api, owner, activity["id"])

    second = api.client.post(
        f"/activities/{activity['id']}/attendance-sessions", headers=owner, json={}
    )
    closed = api.client.post(
        f"/attendance-sessions/{session['id']}/close", headers=owner
    )
    third = open_session(api, owner, activity["id"])

    assert second.json()["detail"] == "session_already_open"
    assert closed.status_code == 204
    assert third["id"] != session["id"]


def test_closed_session_hides_its_codes(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    activity = published(api, owner, make_org(api, owner))
    session = open_session(api, owner, activity["id"])
    api.client.post(f"/attendance-sessions/{session['id']}/close", headers=owner)

    listed = api.client.get(
        f"/activities/{activity['id']}/attendance-sessions", headers=owner
    ).json()

    assert listed[0]["is_open"] is False
    assert listed[0]["manual_code"] is None
    assert listed[0]["qr_token"] is None


def test_qr_scan_counts_at_once(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"], title="Sang")

    response = check_in(api, volunteer, token=session["qr_token"])

    assert response.status_code == 201
    assert response.json()["status"] == "accepted"
    assert response.json()["activity_title"] == activity["title"]
    roster = api.client.get(
        f"/attendance-sessions/{session['id']}/roster", headers=owner
    ).json()
    assert roster[0]["method"] == "qr"
    assert roster[0]["verified"] is True
    with app.state.engine.connect() as connection:
        used = connection.scalar(
            select(QrCode.used_count).where(QrCode.code == session["qr_token"])
        )
        results = connection.scalars(
            select(QrScanLog.result).where(QrScanLog.qr_code == session["qr_token"])
        ).all()
    assert used == 1
    assert results == ["accepted"]


def test_typed_code_waits_for_a_manager(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])

    response = check_in(api, volunteer, code=session["manual_code"].lower())

    assert response.status_code == 201
    assert response.json()["status"] == "pending_review"
    path = f"/attendance-sessions/{session['id']}/roster"
    entry = api.client.get(path, headers=owner).json()[0]
    assert entry["method"] == "manual"
    assert entry["verified"] is False

    verified = api.client.post(
        f"/attendance-records/{entry['record_id']}/verify", headers=owner
    )

    assert verified.status_code == 204
    assert api.client.get(path, headers=owner).json()[0]["verified"] is True


def test_manager_can_refuse_a_typed_code(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, code=session["manual_code"])
    path = f"/attendance-sessions/{session['id']}/roster"
    record_id = api.client.get(path, headers=owner).json()[0]["record_id"]

    deleted = api.client.delete(f"/attendance-records/{record_id}", headers=owner)

    assert deleted.status_code == 204
    assert api.client.get(path, headers=owner).json()[0]["record_id"] is None


def test_manager_can_check_someone_in_by_hand(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    registration = sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    path = f"/attendance-sessions/{session['id']}/records"

    marked = api.client.post(
        path, headers=owner, json={"registration_id": registration["id"]}
    )
    again = api.client.post(
        path, headers=owner, json={"registration_id": registration["id"]}
    )

    assert marked.status_code == 204
    assert again.json()["detail"] == "already_checked_in"


def test_check_in_twice_is_a_conflict(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    activity = published(api, owner, make_org(api, owner))
    sign_up(api, volunteer, activity["id"])
    session = open_session(api, owner, activity["id"])
    check_in(api, volunteer, token=session["qr_token"])

    again = check_in(api, volunteer, token=session["qr_token"])

    assert again.status_code == 409
    assert again.json()["detail"] == "already_checked_in"


def test_shift_session_covers_only_that_shift(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    morning_person, _ = user(api, bearer, "morning")
    evening_person, _ = user(api, bearer, "evening")
    activity = published(api, owner, make_org(api, owner))
    morning = add_shift(api, owner, activity["id"], title="Sang")
    evening = add_shift(api, owner, activity["id"], title="Chieu", start=10.3, end=10.4)
    sign_up(api, morning_person, activity["id"], shift_id=morning["id"])
    sign_up(api, evening_person, activity["id"], shift_id=evening["id"])

    missing = api.client.post(
        f"/activities/{activity['id']}/attendance-sessions", headers=owner, json={}
    )
    session = open_session(api, owner, activity["id"], shift_id=morning["id"])
    accepted = check_in(api, morning_person, token=session["qr_token"])
    refused = check_in(api, evening_person, token=session["qr_token"])
    roster = api.client.get(
        f"/attendance-sessions/{session['id']}/roster", headers=owner
    ).json()

    assert missing.json()["detail"][0]["type"] == "shift_required"
    assert session["shift_title"] == "Sang"
    assert accepted.status_code == 201
    assert refused.json()["detail"] == "not_registered_for_session"
    assert len(roster) == 1
