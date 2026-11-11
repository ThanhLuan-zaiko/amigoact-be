"""The PDF must never outlive a revocation, and bad input must not crash it."""

from pathlib import Path

from tests.activity_helpers import Bearer, make_org, user
from tests.attendance_helpers import attended_activity
from tests.conftest import ApiContext
from tests.media_helpers import uploaded


def test_revoked_certificate_has_no_pdf_until_reinstated(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "revokepdf")
    volunteer, _ = user(api, bearer, "revokepdfvol")
    activity = attended_activity(api, owner, volunteer)
    path = f"/activities/{activity['id']}/certificates"
    api.client.post(path, headers=owner)
    item = api.client.get(path, headers=owner).json()["items"][0]
    pdf = f"/certificates/verify/{item['serial_no']}/pdf"

    api.client.post(
        f"/certificates/{item['id']}/revoke",
        headers=owner,
        json={"reason": "Cap nham nguoi"},
    )
    refused = api.client.get(pdf)
    api.client.post(f"/certificates/{item['id']}/reinstate", headers=owner)
    restored = api.client.get(pdf)

    assert refused.status_code == 409
    assert refused.json()["detail"] == "certificate_not_issued"
    assert restored.status_code == 200


def test_broken_background_prints_a_plain_page(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "brokenbg")
    volunteer, _ = user(api, bearer, "brokenbgvol")
    slug = make_org(api, owner)
    # Passes the upload check by its first bytes, but is not a real picture.
    background = uploaded(api, owner)
    template = api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=owner,
        json={"name": "Hong anh", "background_asset_id": background["id"]},
    ).json()
    activity = attended_activity(api, owner, volunteer, slug=slug)
    path = f"/activities/{activity['id']}/certificates"
    api.client.post(path, headers=owner, json={"template_id": template["id"]})
    serial = api.client.get(path, headers=owner).json()["items"][0]["serial_no"]

    response = api.client.get(f"/certificates/verify/{serial}/pdf")

    assert response.status_code == 200
    assert b"/Subtype /Image" not in response.content


def test_unknown_or_malformed_serial(api: ApiContext) -> None:
    missing = api.client.get("/certificates/verify/AMG-AAAA-AAAA-AAAA/pdf")
    malformed = api.client.get("/certificates/verify/bad.serial/pdf")

    assert missing.status_code == 404
    assert missing.json()["detail"] == "certificate_not_found"
    assert malformed.status_code == 422
