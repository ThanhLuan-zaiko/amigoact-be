import pytest
from pydantic import ValidationError

from src.certificates.schemas import RevokeRequest
from src.certificates.service import new_serial


def test_serial_has_the_expected_shape_and_differs() -> None:
    serial = new_serial()
    parts = serial.split("-")
    assert parts[0] == "AMG"
    assert [len(part) for part in parts[1:]] == [4, 4, 4]
    assert new_serial() != serial


def test_revoking_needs_a_real_reason() -> None:
    with pytest.raises(ValidationError):
        RevokeRequest(reason="abc")
