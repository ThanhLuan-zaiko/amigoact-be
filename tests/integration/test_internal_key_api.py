"""Every HTTP route needs the internal key that the Next.js server sends."""

import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.internal_key import HEADER, INVALID_CODE
from tests.conftest import ApiContext


@pytest.fixture
def outsider() -> TestClient:
    """A caller that reaches the API port directly, without the key."""
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/organizations"),
        ("GET", "/organizations/mine"),
        ("GET", "/feed/public"),
        ("POST", "/auth/login"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
    ],
)
def test_requests_without_the_key_are_refused(
    outsider: TestClient, method: str, path: str
) -> None:
    response = outsider.request(method, path)
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_CODE}


def test_a_wrong_key_is_refused(api: ApiContext) -> None:
    response = api.client.get("/organizations", headers={HEADER: "wrong" * 10})
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_CODE}


def test_the_right_key_reaches_the_route(api: ApiContext) -> None:
    response = api.client.get("/organizations")
    assert response.status_code == 200
    assert "items" in response.json()


def test_refused_request_changes_nothing(api: ApiContext, outsider: TestClient) -> None:
    response = outsider.post(
        "/auth/register",
        json={
            "email": api.email("outsider"),
            "password": "Correct-Horse-7-Battery",
            "full_name": "Outsider",
        },
    )
    assert response.status_code == 401
    # The same email still registers through the keyed client, so no row was written.
    api.register("outsider")
