import uuid

import pytest
from pydantic import ValidationError

from src.organizations.gallery_items import MAX_GALLERY_ITEMS, unique_asset_ids
from src.organizations.schemas import OrganizationCreateRequest
from tests.conftest import ORG_FIELDS


def test_repeated_ids_keep_their_first_place() -> None:
    first, second = uuid.uuid7(), uuid.uuid7()

    assert unique_asset_ids([first, second, first]) == [first, second]


def test_creation_accepts_a_full_gallery_and_no_gallery() -> None:
    ids = [uuid.uuid7() for _ in range(MAX_GALLERY_ITEMS)]

    request = OrganizationCreateRequest(
        **ORG_FIELDS, name="CLB Test", gallery_asset_ids=ids
    )

    assert request.gallery_asset_ids == ids
    assert (
        OrganizationCreateRequest(**ORG_FIELDS, name="CLB Test").gallery_asset_ids == []
    )


def test_creation_rejects_more_than_the_gallery_limit() -> None:
    ids = [uuid.uuid7() for _ in range(MAX_GALLERY_ITEMS + 1)]

    with pytest.raises(ValidationError) as exc:
        OrganizationCreateRequest(**ORG_FIELDS, name="CLB Test", gallery_asset_ids=ids)

    assert exc.value.errors()[0]["type"] == "too_long"
