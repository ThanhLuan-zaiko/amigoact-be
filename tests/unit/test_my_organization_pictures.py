import uuid

import pytest
from pydantic import ValidationError

from src.organizations.schemas import MyOrganization


def base_fields(**extra: object) -> dict[str, object]:
    return {
        "id": uuid.uuid7(),
        "name": "CLB Test",
        "slug": "clb-test",
        "description": None,
        "org_type": "organization",
        "join_policy": "invite",
        "member_count": 1,
        "created_at": "2026-11-03T00:00:00Z",
        "status": "active",
        "role": "owner",
        **extra,
    }


def test_my_organization_carries_both_picture_paths() -> None:
    picture = f"/media/{uuid.uuid7()}/file"

    row = MyOrganization(**base_fields(logo_url=picture, cover_url=None))  # type: ignore[arg-type]

    assert row.logo_url == picture
    assert row.cover_url is None


@pytest.mark.parametrize("missing", ["logo_url", "cover_url"])
def test_my_organization_requires_both_picture_fields(missing: str) -> None:
    fields = base_fields(logo_url=None, cover_url=None)
    del fields[missing]

    with pytest.raises(ValidationError):
        MyOrganization(**fields)  # type: ignore[arg-type]
