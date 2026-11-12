from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, uploaded
from tests.post_helpers import join, open_org


def test_members_and_visitors_cannot_choose_pictures(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "psown")
    member, _ = user(api, bearer, "psmem")
    slug = open_org(api, owner)
    join(api, slug, member)
    url = f"/organizations/{slug}/pictures"

    assert api.client.put(url, json={"logo_asset_id": None}).status_code == 401
    response = api.client.put(url, headers=member, json={"logo_asset_id": None})
    assert response.status_code == 403


def test_someone_elses_upload_is_still_refused(api: ApiContext, bearer: Bearer) -> None:
    """Reuse covers pictures the org shows, not any file a manager knows the id of."""
    owner, _ = user(api, bearer, "psfor")
    stranger, _ = user(api, bearer, "psstr")
    slug = open_org(api, owner)
    foreign = uploaded(api, stranger, PNG + b"9")["id"]

    response = api.client.put(
        f"/organizations/{slug}/pictures",
        headers=owner,
        json={"logo_asset_id": foreign},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "media_not_found"


def test_unknown_fields_are_refused(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "psxtra")
    slug = open_org(api, owner)

    response = api.client.put(
        f"/organizations/{slug}/pictures", headers=owner, json={"slug": "x"}
    )

    assert response.status_code == 422
