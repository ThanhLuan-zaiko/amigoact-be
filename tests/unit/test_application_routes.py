"""HTTP contract for membership application routes over fake ports (no I/O)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.dependencies import CurrentUser, get_current_user, get_member_service
from core.exceptions import DomainError, domain_error_handler
from orgs.application_router import router
from tests.unit.member_fakes import NOW, _new_user, _service, _uid


def _client(service, user_id) -> TestClient:  # noqa: ANN001
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.dependency_overrides[get_member_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=user_id, email="x@example.com", status="active"
    )
    return TestClient(app)


def test_form_put_is_manager_only_and_get_is_open_to_signed_in_users() -> None:
    service, _, members, users, _, org_id, owner = _service("review")
    plain = _new_user(users, "plain@example.com")
    members.put(org_id, plain, "active", NOW)
    body = {"questions": [{"label": "Why?", "field_type": "textarea", "required": True}]}

    denied = _client(service, plain).put(f"/orgs/{org_id}/membership-form", json=body)
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")

    saved = _client(service, owner).put(f"/orgs/{org_id}/membership-form", json=body)
    assert saved.status_code == 200
    questions = saved.json()["questions"]
    assert [q["label"] for q in questions] == ["Why?"]
    assert questions[0]["required"] is True

    read = _client(service, plain).get(f"/orgs/{org_id}/membership-form")
    assert read.status_code == 200
    assert read.json()["questions"][0]["field_type"] == "textarea"


def test_form_rejects_unknown_field_type() -> None:
    service, _, _, _, _, org_id, owner = _service("review")
    body = {"questions": [{"label": "Video?", "field_type": "video"}]}
    response = _client(service, owner).put(f"/orgs/{org_id}/membership-form", json=body)
    assert response.status_code == 422


def test_apply_returns_201_with_location_and_applied_status() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    service.replace_membership_form(org_id, owner, [("Why?", "text", True, [], False)])
    applicant = _new_user(users, "a@example.com")
    client = _client(service, applicant)
    question_id = str(service.list_membership_form(org_id)[0].question_id)

    created = client.post(
        f"/orgs/{org_id}/members/apply", json={"answers": {question_id: "Kids"}}
    )
    assert created.status_code == 201
    assert created.headers["Location"] == f"/orgs/{org_id}/members/{applicant}"
    assert created.json()["status"] == "applied"


def test_apply_error_codes_match_contract() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    service.replace_membership_form(org_id, owner, [("Why?", "text", True, [], False)])
    applicant = _new_user(users, "a@example.com")
    client = _client(service, applicant)
    path = f"/orgs/{org_id}/members/apply"

    missing = client.post(path, json={"answers": {}})
    assert (missing.status_code, missing.json()["code"]) == (400, "ANSWER_REQUIRED")

    question_id = str(service.list_membership_form(org_id)[0].question_id)
    client.post(path, json={"answers": {question_id: "Kids"}})
    again = client.post(path, json={"answers": {question_id: "Kids"}})
    assert (again.status_code, again.json()["code"]) == (409, "ALREADY_APPLIED")


def test_open_org_answers_apply_with_not_accepting() -> None:
    service, _, _, users, _, org_id, _ = _service("open")
    applicant = _new_user(users, "a@example.com")
    response = _client(service, applicant).post(
        f"/orgs/{org_id}/members/apply", json={"answers": {}}
    )
    assert (response.status_code, response.json()["code"]) == (
        403,
        "NOT_ACCEPTING_APPLICATIONS",
    )


def test_review_reads_answers_then_approves_and_rejects() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    service.replace_membership_form(org_id, owner, [("Why?", "text", False, [], False)])
    applicant = _new_user(users, "a@example.com")
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    _client(service, applicant).post(
        f"/orgs/{org_id}/members/apply", json={"answers": {question_id: "Kids"}}
    )
    reviewer = _client(service, owner)
    base = f"/orgs/{org_id}/members/{applicant}"

    read = reviewer.get(f"{base}/application")
    assert read.status_code == 200
    assert read.json()["answers"] == [
        {"question_id": question_id, "label": "Why?", "answer": "Kids", "is_other": False, "file": None}
    ]

    early = reviewer.post(f"/orgs/{org_id}/members/{_uid()}/approve")
    assert (early.status_code, early.json()["code"]) == (400, "INVALID_MEMBER_STATE")

    approved = reviewer.post(f"{base}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"

    not_pending = reviewer.post(f"{base}/reject")
    assert (not_pending.status_code, not_pending.json()["code"]) == (
        400,
        "INVALID_MEMBER_STATE",
    )
