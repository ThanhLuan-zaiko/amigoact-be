"""Validators shared by every API module.

Errors use PydanticCustomError, so their `type` is a stable code for clients.
"""

import re
import uuid
from typing import Annotated

from fastapi import HTTPException, status
from pydantic import AfterValidator
from pydantic_core import PydanticCustomError

UUID_V7 = 7
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
# Multi-line text may keep tabs and line breaks. NUL would also crash PostgreSQL.
_CONTROL_EXCEPT_LAYOUT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def _text_invalid() -> PydanticCustomError:
    return PydanticCustomError("text_invalid", "Text has control characters")


def single_line(value: str) -> str:
    """Reject control characters and collapse runs of spaces."""
    if _CONTROL_CHARACTERS.search(value):
        raise _text_invalid()
    return _WHITESPACE.sub(" ", value).strip()


def multi_line(value: str) -> str:
    """Reject control characters except layout, and use one kind of line break."""
    if _CONTROL_EXCEPT_LAYOUT.search(value):
        raise _text_invalid()
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def require_uuid7(value: uuid.UUID) -> uuid.UUID:
    """Every primary key in the system is a UUIDv7, so other versions cannot match."""
    if value.version != UUID_V7:
        raise PydanticCustomError("uuid_invalid", "ID must be a UUIDv7")
    return value


Uuid7 = Annotated[uuid.UUID, AfterValidator(require_uuid7)]


def validation_failure(errors: dict[str, str]) -> HTTPException:
    """Report rules that need the database in the same shape as schema errors.

    Maps each field name to its stable error code.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {"type": code, "loc": ["body", field], "msg": code}
            for field, code in errors.items()
        ],
    )
