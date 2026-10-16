"""Unit tests for the shared {code, message} error envelope handlers."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import cast

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth.schemas import validate_date_of_birth
from core.exceptions import (
    http_error_handler,
    validation_error_handler,
    validation_message,
)


def _request() -> Request:
    return cast(Request, None)


def test_validation_message_formats_first_error() -> None:
    errors = [
        {"loc": ("body", "tax_code"), "msg": "Field required"},
        {"loc": ("body", "slug"), "msg": "Too short"},
    ]
    assert validation_message(errors) == "tax_code: Field required"


def test_validation_message_keeps_query_location() -> None:
    errors = [{"loc": ("query", "sort"), "msg": "Input should be 'newest'"}]
    assert validation_message(errors) == "query.sort: Input should be 'newest'"


def test_validation_message_handles_empty_list() -> None:
    assert validation_message([]) == "Request validation failed."


async def test_validation_error_handler_envelope() -> None:
    exc = RequestValidationError(
        [{"loc": ("body", "email"), "msg": "Input should be a valid email"}]
    )
    response = await validation_error_handler(_request(), exc)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["code"] == "VALIDATION_ERROR"
    assert "email" in body["message"]


async def test_http_error_handler_maps_404_to_not_found() -> None:
    response = await http_error_handler(
        _request(), StarletteHTTPException(404, "Not Found")
    )
    assert response.status_code == 404
    assert json.loads(response.body)["code"] == "NOT_FOUND"


async def test_http_error_handler_other_statuses() -> None:
    response = await http_error_handler(
        _request(), StarletteHTTPException(405, "Method Not Allowed")
    )
    assert response.status_code == 405
    assert json.loads(response.body)["code"] == "REQUEST_FAILED"


def test_date_of_birth_rejects_future_and_accepts_today() -> None:
    today = datetime.now(timezone.utc).date()
    assert validate_date_of_birth(today) == today
    with pytest.raises(ValueError):
        validate_date_of_birth(today + timedelta(days=1))
    with pytest.raises(ValueError):
        validate_date_of_birth(date(1899, 12, 31))
