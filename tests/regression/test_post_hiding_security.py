from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.post_helpers import comment, created, join, open_org


def test_members_and_authors_cannot_hide(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "hsown")
    member, _ = user(api, bearer, "hsmem")
    slug = open_org(api, owner)
    join(api, slug, member)
    talk = created(api, member, slug, title="Cua toi", visibility="public")

    response = api.client.post(f"/posts/{talk['id']}/hide", headers=member)

    assert response.status_code == 403
    assert response.json()["detail"] == "post_forbidden"
    assert talk["viewer"]["can_hide"] is False


def test_drafts_cannot_be_hidden(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "hsdraft")
    slug = open_org(api, owner)
    draft = created(api, owner, slug, kind="announcement", draft=True)

    response = api.client.post(f"/posts/{draft['id']}/hide", headers=owner)

    assert response.status_code == 409
    assert response.json()["detail"] == "post_not_published"


def test_hidden_post_blocks_its_author_and_comments(
    api: ApiContext, bearer: Bearer
) -> None:
    """The author is not a manager, so a hidden post is gone for them too."""
    owner, _ = user(api, bearer, "hsauth")
    member, _ = user(api, bearer, "hsauthm")
    slug = open_org(api, owner)
    join(api, slug, member)
    talk = created(api, member, slug, title="Bi an", visibility="public")
    assert (
        api.client.post(f"/posts/{talk['id']}/hide", headers=owner).status_code == 204
    )

    assert api.client.get(f"/posts/{talk['id']}", headers=member).status_code == 404
    assert comment(api, member, talk["id"], "Con day").status_code == 404
    unhide = api.client.post(f"/posts/{talk['id']}/unhide", headers=member)
    assert unhide.status_code == 404


def test_visitors_cannot_hide(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "hsvis")
    slug = open_org(api, owner)
    notice = created(api, owner, slug, kind="announcement")

    assert api.client.post(f"/posts/{notice['id']}/hide").status_code == 401
