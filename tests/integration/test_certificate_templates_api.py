import uuid
from pathlib import Path
from typing import Any

from src.models.certificates import Certificate, CertificateTemplate
from src.models.media import MediaAsset
from tests.activity_helpers import Bearer, Headers, make_org, user
from tests.attendance_helpers import attended_activity
from tests.conftest import ApiContext
from tests.media_helpers import db_row, uploaded


def create(api: ApiContext, headers: Headers, slug: str, **body: Any) -> Any:
    return api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=headers,
        json={"name": "Giay khen", **body},
    )


def test_manager_creates_a_template_with_default_layout(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)

    response = create(api, owner, slug)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Giay khen"
    assert body["is_active"] is True
    assert body["background_url"] is None
    assert set(body["layout"]) == {"name", "activity", "hours", "date", "serial"}
    row = db_row(CertificateTemplate, uuid.UUID(body["id"]))
    assert row.layout_json == body["layout"]


def test_background_is_public_once_it_is_on_a_template(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "bg")
    slug = make_org(api, owner)
    background = uploaded(api, owner)

    response = create(api, owner, slug, background_asset_id=background["id"])

    assert response.status_code == 201, response.text
    assert response.json()["background_url"] == background["url"]
    assert db_row(MediaAsset, uuid.UUID(background["id"])).visibility == "public"
    assert api.client.get(background["url"]).status_code == 200


def test_manager_lists_inactive_templates_too(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "list")
    slug = make_org(api, owner)
    kept = create(api, owner, slug, name="Giu lai").json()
    archived = create(api, owner, slug, name="Luu tru").json()
    api.client.patch(
        f"/certificate-templates/{archived['id']}",
        headers=owner,
        json={"is_active": False},
    )

    response = api.client.get(
        f"/organizations/{slug}/certificate-templates", headers=owner
    )

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[kept["id"]]["is_active"] is True
    assert items[archived["id"]]["is_active"] is False


def test_update_changes_only_what_is_sent(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "patch")
    slug = make_org(api, owner)
    background = uploaded(api, owner)
    template = create(api, owner, slug, background_asset_id=background["id"]).json()

    renamed = api.client.patch(
        f"/certificate-templates/{template['id']}",
        headers=owner,
        json={"name": "Doi ten", "layout": {"name": {"x": 20, "y": 30, "size": 40}}},
    )

    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["name"] == "Doi ten"
    assert body["layout"]["name"] == {"x": 20, "y": 30, "size": 40}
    assert body["layout"]["hours"] == {"x": 50, "y": 62, "size": 14}
    assert body["background_url"] == background["url"]

    removed = api.client.patch(
        f"/certificate-templates/{template['id']}",
        headers=owner,
        json={"background_asset_id": None},
    )
    assert removed.status_code == 200
    assert removed.json()["background_url"] is None
    assert removed.json()["name"] == "Doi ten"


def test_issue_stores_the_template_on_each_certificate(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "issuer")
    volunteer, _ = user(api, bearer, "volunteer")
    slug = make_org(api, owner)
    template = create(api, owner, slug).json()
    activity = attended_activity(api, owner, volunteer, slug=slug)

    issued = api.client.post(
        f"/activities/{activity['id']}/certificates",
        headers=owner,
        json={"template_id": template["id"]},
    )

    assert issued.status_code == 200, issued.text
    assert issued.json() == {"issued": 1}
    mine = api.client.get("/certificates/mine", headers=volunteer).json()
    certificate = db_row(Certificate, uuid.UUID(mine[0]["id"]))
    assert certificate.template_id == uuid.UUID(template["id"])


def test_issue_without_a_template_leaves_it_empty(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "plain")
    volunteer, _ = user(api, bearer, "plainvol")
    activity = attended_activity(api, owner, volunteer)

    issued = api.client.post(
        f"/activities/{activity['id']}/certificates", headers=owner
    )

    assert issued.status_code == 200
    mine = api.client.get("/certificates/mine", headers=volunteer).json()
    assert db_row(Certificate, uuid.UUID(mine[0]["id"])).template_id is None


def test_inactive_template_cannot_be_issued(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "retired")
    volunteer, _ = user(api, bearer, "retiredvol")
    slug = make_org(api, owner)
    template = create(api, owner, slug).json()
    api.client.patch(
        f"/certificate-templates/{template['id']}",
        headers=owner,
        json={"is_active": False},
    )
    activity = attended_activity(api, owner, volunteer, slug=slug)

    response = api.client.post(
        f"/activities/{activity['id']}/certificates",
        headers=owner,
        json={"template_id": template["id"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "certificate_template_inactive"
    assert api.client.get("/certificates/mine", headers=volunteer).json() == []


def test_template_of_another_organization_is_not_found(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "mine")
    other, _ = user(api, bearer, "theirs")
    volunteer, _ = user(api, bearer, "vol")
    their_template = create(api, other, make_org(api, other)).json()
    activity = attended_activity(api, owner, volunteer)

    response = api.client.post(
        f"/activities/{activity['id']}/certificates",
        headers=owner,
        json={"template_id": their_template["id"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "certificate_template_not_found"
