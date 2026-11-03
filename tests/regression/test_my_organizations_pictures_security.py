from collections.abc import Callable
from pathlib import Path

from tests.activity_helpers import make_org, user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, uploaded

Bearer = Callable[[str], dict[str, str]]


def test_a_picture_that_is_only_uploaded_is_not_shown_on_any_card(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "not-attached")
    slug = make_org(api, headers)
    uploaded(api, headers, PNG)  # uploaded, never attached to the organization

    rows = api.client.get("/organizations/mine", headers=headers).json()

    row = next(item for item in rows if item["slug"] == slug)
    assert row["logo_url"] is None
    assert row["cover_url"] is None


def test_a_member_sees_the_same_logo_path_as_the_owner(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "logo-owner")
    member, _ = user(api, bearer, "logo-member")
    slug = make_org(api, owner)
    logo = uploaded(api, owner, PNG)
    api.client.put(
        f"/organizations/{slug}/logo", headers=owner, json={"asset_id": logo["id"]}
    )
    api.client.post(f"/organizations/{slug}/join", headers=member, json={})

    rows = api.client.get("/organizations/mine", headers=member).json()

    row = next(item for item in rows if item["slug"] == slug)
    assert row["logo_url"] == f"/media/{logo['id']}/file"
    # The file route still decides who may read the bytes, so the path alone is safe.
    assert api.client.get(row["logo_url"], headers=member).status_code == 200
