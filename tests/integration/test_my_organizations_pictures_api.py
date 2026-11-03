from collections.abc import Callable
from pathlib import Path

from tests.activity_helpers import make_org, user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, WEBP, uploaded

Bearer = Callable[[str], dict[str, str]]


def mine_row(api: ApiContext, headers: dict[str, str], slug: str) -> dict[str, object]:
    rows = api.client.get("/organizations/mine", headers=headers).json()
    return next(row for row in rows if row["slug"] == slug)


def test_mine_shows_the_logo_and_cover_paths_for_the_card(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "card-owner")
    slug = make_org(api, headers)
    logo = uploaded(api, headers, PNG)
    cover = uploaded(api, headers, WEBP)
    api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": logo["id"]}
    )
    api.client.put(
        f"/organizations/{slug}/cover", headers=headers, json={"asset_id": cover["id"]}
    )

    row = mine_row(api, headers, slug)

    assert row["logo_url"] == f"/media/{logo['id']}/file"
    assert row["cover_url"] == f"/media/{cover['id']}/file"


def test_mine_shows_null_once_the_pictures_are_cleared(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "clearing-owner")
    slug = make_org(api, headers)
    logo = uploaded(api, headers, PNG)
    api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": logo["id"]}
    )

    api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": None}
    )

    row = mine_row(api, headers, slug)
    assert row["logo_url"] is None
    assert row["cover_url"] is None


def test_public_list_shows_the_pictures_of_each_organization(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "listed-owner")
    slug = make_org(api, headers)
    logo = uploaded(api, headers, PNG)
    api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": logo["id"]}
    )

    page = api.client.get("/organizations", params={"q": api.tag}).json()

    row = next(item for item in page["items"] if item["slug"] == slug)
    assert row["logo_url"] == f"/media/{logo['id']}/file"
    assert row["cover_url"] is None
