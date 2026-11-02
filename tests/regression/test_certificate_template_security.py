import uuid
from pathlib import Path
from typing import Any

from src.models.certificates import CertificateTemplate
from tests.activity_helpers import Bearer, Headers, make_org, user
from tests.conftest import ApiContext
from tests.media_helpers import db_row, uploaded


def create(api: ApiContext, headers: Headers, slug: str, **body: Any) -> Any:
    return api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=headers,
        json={"name": "Giay khen", **body},
    )


def test_outsider_cannot_create_or_list_templates(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "org")
    outsider, _ = user(api, bearer, "out")
    slug = make_org(api, owner)

    created = create(api, outsider, slug)
    listed = api.client.get(
        f"/organizations/{slug}/certificate-templates", headers=outsider
    )

    assert created.status_code == 403
    assert created.json()["detail"] == "organization_forbidden"
    assert listed.status_code == 403


def test_outsider_cannot_change_someone_elses_template(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    outsider, _ = user(api, bearer, "out2")
    template = create(api, owner, make_org(api, owner)).json()

    response = api.client.patch(
        f"/certificate-templates/{template['id']}",
        headers=outsider,
        json={"name": "Bi doi"},
    )

    assert response.status_code == 403
    assert db_row(CertificateTemplate, uuid.UUID(template["id"])).name == "Giay khen"


def test_someone_elses_background_cannot_be_used(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "bgowner")
    thief, _ = user(api, bearer, "thief")
    private_file = uploaded(api, thief)

    response = create(
        api, owner, make_org(api, owner), background_asset_id=private_file["id"]
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "media_not_found"
    assert api.client.get(private_file["url"], headers=owner).status_code == 404


def test_layout_refuses_unknown_texts_and_out_of_range_values(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "layout")
    slug = make_org(api, owner)

    unknown = create(api, owner, slug, layout={"logo": {"x": 1, "y": 1, "size": 10}})
    off_page = create(api, owner, slug, layout={"name": {"x": 150, "y": 1, "size": 10}})

    assert unknown.status_code == 422
    assert off_page.status_code == 422


def test_template_body_refuses_fields_it_does_not_own(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "fields")
    slug = make_org(api, owner)

    response = create(api, owner, slug, org_id=str(uuid.uuid4()))

    assert response.status_code == 422


def test_control_characters_in_the_name_are_refused(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "name")

    response = create(api, owner, make_org(api, owner), name="Giay\x00khen")

    assert response.status_code == 422


def test_template_path_must_be_a_uuid7(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "path")

    response = api.client.patch(
        f"/certificate-templates/{uuid.uuid4()}",
        headers=owner,
        json={"name": "Thu"},
    )

    assert response.status_code == 422


def test_unknown_template_is_not_found(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "missing")

    response = api.client.patch(
        f"/certificate-templates/{uuid.uuid7()}",
        headers=owner,
        json={"name": "Thu"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "certificate_template_not_found"
