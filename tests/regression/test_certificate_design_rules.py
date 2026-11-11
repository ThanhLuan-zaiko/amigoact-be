"""Behavior the certificate design must keep.

- Turning a template off hides it from new issues only. Certificates already issued
  with it keep their look, so a printout does not change after the fact.
- The public design never names the template or its organization's internals.
"""

from typing import Any

from tests.activity_helpers import Bearer, make_org, user
from tests.attendance_helpers import attended_activity
from tests.conftest import ApiContext


def issued_serial(
    api: ApiContext, bearer: Bearer, label: str
) -> tuple[dict[str, str], str, dict[str, Any]]:
    owner, _ = user(api, bearer, label)
    volunteer, _ = user(api, bearer, f"{label}vol")
    slug = make_org(api, owner)
    template = api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=owner,
        json={"name": "Mau bi mat"},
    ).json()
    activity = attended_activity(api, owner, volunteer, slug=slug)
    path = f"/activities/{activity['id']}/certificates"
    api.client.post(path, headers=owner, json={"template_id": template["id"]})
    serial = api.client.get(path, headers=owner).json()["items"][0]["serial_no"]
    return owner, serial, template


def test_turning_a_template_off_keeps_the_design_of_issued_certificates(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, serial, template = issued_serial(api, bearer, "retire")
    before = api.client.get(f"/certificates/verify/{serial}").json()["design"]

    api.client.patch(
        f"/certificate-templates/{template['id']}",
        headers=owner,
        json={"is_active": False},
    )
    after = api.client.get(f"/certificates/verify/{serial}").json()["design"]

    assert before is not None
    assert after == before


def test_public_design_does_not_reveal_the_template(
    api: ApiContext, bearer: Bearer
) -> None:
    _, serial, template = issued_serial(api, bearer, "private")

    response = api.client.get(f"/certificates/verify/{serial}")

    assert response.status_code == 200
    assert set(response.json()["design"]) == {"background_url", "layout"}
    assert template["id"] not in response.text
    assert "Mau bi mat" not in response.text
