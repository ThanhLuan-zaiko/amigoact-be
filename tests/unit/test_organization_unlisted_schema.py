"""The listing flag accepts only real booleans, and omitting it changes nothing."""

import pytest
from pydantic import ValidationError

from src.organizations.schemas import OrganizationUpdateRequest


def test_listing_flag_accepts_true_and_false() -> None:
    assert OrganizationUpdateRequest(listed_publicly=False).listed_publicly is False
    assert OrganizationUpdateRequest(listed_publicly=True).listed_publicly is True


@pytest.mark.parametrize("value", [None, "false", 0])
def test_listing_flag_rejects_non_boolean_values(value: object) -> None:
    with pytest.raises(ValidationError):
        OrganizationUpdateRequest(listed_publicly=value)  # type: ignore[arg-type]


def test_omitted_listing_flag_is_not_sent() -> None:
    body = OrganizationUpdateRequest(name="Ten moi")

    assert "listed_publicly" not in body.model_fields_set
