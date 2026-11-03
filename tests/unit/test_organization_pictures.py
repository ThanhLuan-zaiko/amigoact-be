import uuid

import pytest
from pydantic import ValidationError

from src.organizations.pictures import picture_url
from src.organizations.schemas import (
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
)
from tests.conftest import ORG_FIELDS


def test_picture_url_is_the_media_path_or_none() -> None:
    media_id = uuid.uuid7()

    assert picture_url(media_id) == f"/media/{media_id}/file"
    assert picture_url(None) is None


def test_create_request_normalizes_the_tax_code() -> None:
    request = OrganizationCreateRequest(
        **ORG_FIELDS, name="CLB Test", tax_code="0101234567001"
    )

    assert request.tax_code == "0101234567-001"


def test_create_request_accepts_legal_details() -> None:
    request = OrganizationCreateRequest(
        **ORG_FIELDS,
        name="CLB Test",
        legal_name="Cong ty Test",
        license_number="QD-12/2026",
        legal_rep_name="Nguyen Van A",
        legal_rep_position="Giam doc",
    )

    assert request.legal_name == "Cong ty Test"
    assert request.license_number == "QD-12/2026"
    assert request.legal_rep_position == "Giam doc"


def test_create_request_rejects_a_bad_tax_code() -> None:
    with pytest.raises(ValidationError) as exc:
        OrganizationCreateRequest(**ORG_FIELDS, name="CLB Test", tax_code="123")

    assert exc.value.errors()[0]["type"] == "tax_code_invalid"


def test_legal_status_is_not_a_writable_field() -> None:
    with pytest.raises(ValidationError) as exc:
        OrganizationCreateRequest(
            **ORG_FIELDS, name="CLB Test", legal_status="verified"
        )  # type: ignore[call-arg]

    assert exc.value.errors()[0]["type"] == "extra_forbidden"


def test_update_request_tracks_a_null_picture_as_a_change() -> None:
    request = OrganizationUpdateRequest(logo_asset_id=None)

    assert request.model_fields_set == {"logo_asset_id"}
    assert request.logo_asset_id is None


def test_update_request_rejects_a_picture_id_that_is_not_uuid7() -> None:
    with pytest.raises(ValidationError):
        OrganizationUpdateRequest(cover_asset_id=str(uuid.uuid4()))
