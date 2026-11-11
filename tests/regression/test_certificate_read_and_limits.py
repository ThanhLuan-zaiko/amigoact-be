"""Reading one template stays with managers, and the public lookup is rate limited."""

import uuid

from src.certificates.router import VERIFY_LIMIT
from tests.activity_helpers import Bearer, make_org, user
from tests.conftest import ApiContext


def test_outsider_cannot_read_a_template(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    outsider, _ = user(api, bearer, "outsider")
    slug = make_org(api, owner)
    template = api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=owner,
        json={"name": "Rieng tu"},
    ).json()

    response = api.client.get(
        f"/certificate-templates/{template['id']}", headers=outsider
    )
    anonymous = api.client.get(f"/certificate-templates/{template['id']}")

    assert response.status_code == 403
    assert response.json()["detail"] == "organization_forbidden"
    assert anonymous.status_code == 401


def test_unknown_or_malformed_template_id(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "unknown")

    missing = api.client.get(f"/certificate-templates/{uuid.uuid7()}", headers=owner)
    malformed = api.client.get(f"/certificate-templates/{uuid.uuid4()}", headers=owner)

    assert missing.status_code == 404
    assert missing.json()["detail"] == "certificate_template_not_found"
    assert malformed.status_code == 422


def test_public_lookup_is_rate_limited_per_client(api: ApiContext) -> None:
    path = "/certificates/verify/AMG-AAAA-AAAA-AAAA"
    for _ in range(VERIFY_LIMIT):
        assert api.client.get(path).status_code == 404

    response = api.client.get(path)

    assert response.status_code == 429
    assert response.json()["detail"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 0
