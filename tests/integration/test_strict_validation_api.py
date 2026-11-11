"""Numbers must arrive as numbers and text as text, across the API."""

from typing import Any

from tests.activity_helpers import Bearer, at, make_org, user
from tests.conftest import ApiContext
from tests.post_helpers import open_org, post


def _types(response: Any) -> dict[str, str]:
    assert response.status_code == 422, response.text
    return {item["loc"][-1]: item["type"] for item in response.json()["detail"]}


def _activity(**fields: Any) -> dict[str, Any]:
    return {
        "title": "Hoat dong mua he",
        "description": "Mo ta",
        "city": "Ha Noi",
        "hours_awarded": "2",
        "location": "San truong",
        "start_at": at(10),
        "end_at": at(11),
        **fields,
    }


def test_post_refuses_wrong_types(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "sv1")
    slug = open_org(api, owner)

    assert _types(post(api, owner, slug, title="2024")) == {
        "title": "text_needs_letter"
    }
    assert _types(post(api, owner, slug, draft="true")) == {"draft": "bool_type"}
    assert _types(post(api, owner, slug, title=123)) == {"title": "string_type"}
    assert _types(post(api, owner, slug, tags="a,b")) == {"tags": "list_type"}


def test_activity_refuses_numbers_as_strings(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "sv2")
    slug = make_org(api, owner)
    path = f"/organizations/{slug}/activities"

    cases = {
        "max_participants": ("5", "int_type"),
        "hours_awarded": ("1e3", "number_invalid"),
        "is_remote": ("true", "bool_type"),
        "requires_approval": (1, "bool_type"),
        "title": ("12345", "text_needs_letter"),
    }
    for field, (value, code) in cases.items():
        response = api.client.post(
            path, headers=owner, json=_activity(**{field: value})
        )
        assert _types(response) == {field: code}, field


def test_activity_accepts_real_numbers(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "sv3")
    slug = make_org(api, owner)

    response = api.client.post(
        f"/organizations/{slug}/activities",
        headers=owner,
        json=_activity(max_participants=5, hours_awarded=2.5, is_remote=True),
    )

    assert response.status_code == 201, response.text
    assert response.json()["hours_awarded"] == 2.5


def test_hour_rule_refuses_flags_and_exponents(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "sv4")
    slug = make_org(api, owner)
    path = f"/organizations/{slug}/hour-rule"

    flag = api.client.put(path, headers=owner, json={"multiplier": True})
    exponent = api.client.put(path, headers=owner, json={"multiplier": "1e0"})
    good = api.client.put(path, headers=owner, json={"multiplier": "1.5"})

    assert _types(flag) == {"multiplier": "number_invalid"}
    assert _types(exponent) == {"multiplier": "number_invalid"}
    assert good.status_code == 200, good.text
