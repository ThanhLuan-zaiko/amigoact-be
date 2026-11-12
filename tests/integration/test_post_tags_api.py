"""GET /organizations/{slug}/post-tags suggests tags already used in the organization."""

from httpx2 import Response

from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.post_helpers import created, join, open_org


def _suggest(
    api: ApiContext, headers: dict[str, str], slug: str, query: str = ""
) -> Response:
    return api.client.get(
        f"/organizations/{slug}/post-tags", headers=headers, params={"q": query}
    )


def test_empty_query_lists_tags_most_used_first(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tagown")
    slug = open_org(api, owner)
    created(api, owner, slug, tags=["Hi\u1ebfn m\u00e1u", "M\u00f4i tr\u01b0\u1eddng"])
    created(api, owner, slug, tags=["moi truong"])

    response = _suggest(api, owner, slug)

    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {"name": "M\u00f4i tr\u01b0\u1eddng", "slug": "moi-truong", "count": 2},
        {"name": "Hi\u1ebfn m\u00e1u", "slug": "hien-mau", "count": 1},
    ]


def test_query_matches_the_start_of_any_word_without_accents(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tagq")
    slug = open_org(api, owner)
    created(api, owner, slug, tags=["M\u00f4i tr\u01b0\u1eddng", "Tr\u1ed3ng c\u00e2y"])
    created(api, owner, slug, tags=["Hi\u1ebfn m\u00e1u"])

    by_second_word = _suggest(api, owner, slug, "TRU").json()["items"]
    by_first_word = _suggest(api, owner, slug, "tr\u1ed3").json()["items"]
    inside_a_word = _suggest(api, owner, slug, "uong").json()["items"]

    assert [item["slug"] for item in by_second_word] == ["moi-truong"]
    assert [item["slug"] for item in by_first_word] == ["trong-cay"]
    assert inside_a_word == []


def test_any_active_member_gets_suggestions_and_limit_is_kept(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "taglim")
    member, _ = user(api, bearer, "tagmem")
    slug = open_org(api, owner)
    join(api, slug, member)
    created(api, owner, slug, tags=["a1", "b2", "c3"])

    response = api.client.get(
        f"/organizations/{slug}/post-tags", headers=member, params={"limit": 2}
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_query_without_letters_or_digits_finds_nothing(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tagsym")
    slug = open_org(api, owner)
    created(api, owner, slug, tags=["Tinh nguyen"])

    assert _suggest(api, owner, slug, "%%").json()["items"] == []
