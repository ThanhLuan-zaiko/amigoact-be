"""Unit tests for individual/business tiers and legal identity."""

from __future__ import annotations

import pytest

from auth.schemas import RegisterRequest
from core.exceptions import InvalidBusinessProfileError
from tests.unit.auth_fakes import make_service as _service

BUSINESS = {
    "email": "biz@example.com",
    "phone": "0912345678",
    "password": "Aa1!secure",
    "full_name": "Cong Ty ABC",
    "account_type": "business",
    "tax_code": "0312345678",
    "company_name": "Cong Ty ABC",
    "legal_rep_name": "Nguyen Van A",
    "legal_rep_id": "012345678901",
    "legal_rep_position": "Giam doc",
}


def test_business_register_stores_legal_identity() -> None:
    service, parts = _service()
    payload = RegisterRequest(**BUSINESS)
    profile = service.register(
        payload.email,
        payload.phone,
        payload.password,
        payload.full_name,
        payload.account_type,
        payload.tax_code,
        payload.company_name,
        payload.legal_rep_name,
        payload.legal_rep_id,
        payload.legal_rep_position,
    )
    assert profile.account_type == "business"
    assert parts["users"].get_by_email(payload.email).tax_code == "0312345678"


def test_business_register_rejects_missing_identity() -> None:
    service, _ = _service()
    with pytest.raises(InvalidBusinessProfileError):
        service.register(
            "b2@example.com", "0312345678", "Aa1!secure", "Biz", "business"
        )


def test_business_schema_rejects_bad_tax_and_cccd() -> None:
    bad_tax = dict(BUSINESS, email="t@example.com", tax_code="1111111111")
    with pytest.raises(ValueError):
        RegisterRequest(**bad_tax)
    bad_cccd = dict(BUSINESS, email="c@example.com", legal_rep_id="123")
    with pytest.raises(ValueError):
        RegisterRequest(**bad_cccd)
