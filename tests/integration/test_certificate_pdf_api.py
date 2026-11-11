from pathlib import Path
from typing import Any

from tests.activity_helpers import Bearer, Headers, make_org, user
from tests.attendance_helpers import attended_activity
from tests.conftest import ApiContext
from tests.media_helpers import uploaded
from tests.pdf_helpers import picture_bytes


def issued_item(
    api: ApiContext, owner: Headers, activity_id: str, **body: Any
) -> dict[str, Any]:
    path = f"/activities/{activity_id}/certificates"
    assert api.client.post(path, headers=owner, json=body).status_code == 200
    item: dict[str, Any] = api.client.get(path, headers=owner).json()["items"][0]
    return item


def test_anyone_downloads_the_pdf_drawn_from_the_template(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "pdfowner")
    volunteer, _ = user(api, bearer, "pdfvol")
    slug = make_org(api, owner)
    background = uploaded(api, owner, picture_bytes("PNG"))
    template = api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=owner,
        json={"name": "Giay khen", "background_asset_id": background["id"]},
    ).json()
    activity = attended_activity(api, owner, volunteer, slug=slug)
    item = issued_item(api, owner, activity["id"], template_id=template["id"])

    response = api.client.get(f"/certificates/verify/{item['serial_no'].lower()}/pdf")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert (
        f"certificate-{item['serial_no']}.pdf"
        in (response.headers["content-disposition"])
    )
    assert response.content.startswith(b"%PDF")
    assert b"/Subtype /Image" in response.content


def test_certificate_without_template_still_prints(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "plainpdf")
    volunteer, _ = user(api, bearer, "plainpdfvol")
    activity = attended_activity(api, owner, volunteer)
    item = issued_item(api, owner, activity["id"])

    response = api.client.get(f"/certificates/verify/{item['serial_no']}/pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert b"/Subtype /Image" not in response.content
