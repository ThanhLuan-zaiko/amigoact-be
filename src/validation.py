"""Validators shared by every API module.

Errors use PydanticCustomError, so their `type` is a stable code for clients.
"""

import math
import re
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import HTTPException, status
from pydantic import AfterValidator, BeforeValidator, Field, Strict
from pydantic_core import PydanticCustomError

UUID_V7 = 7
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
# Multi-line text may keep tabs and line breaks. NUL would also crash PostgreSQL.
_CONTROL_EXCEPT_LAYOUT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
# A plain decimal: digits, an optional dot with digits, and an optional leading minus.
# No spaces, no exponent, no "NaN" or "Infinity".
_PLAIN_DECIMAL = re.compile(r"-?[0-9]+(\.[0-9]+)?")


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


def has_letter(value: str) -> str:
    """Text a person reads as a name or a title needs at least one letter.

    "2024", "!!!" and "123-456" are refused, so a title cannot be only digits or marks.
    """
    if not any(character.isalpha() for character in value):
        raise PydanticCustomError("text_needs_letter", "Text needs a letter")
    return value


def _number_invalid() -> PydanticCustomError:
    return PydanticCustomError("number_invalid", "Value must be a plain number")


def decimal_input(value: object) -> object:
    """Accept a JSON number or a plain decimal string, and nothing else.

    True and False are refused, although Python treats them as 1 and 0. So are
    "1e3", " 2 ", "NaN", "Infinity", and any other type.
    """
    if isinstance(value, bool):
        raise _number_invalid()
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _number_invalid()
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise _number_invalid()
        return value
    if isinstance(value, str) and _PLAIN_DECIMAL.fullmatch(value):
        return value
    raise _number_invalid()


# Numbers that must arrive as numbers. "5" is refused for an integer (int_type), a
# string is refused for a float (float_type), and "true" or 1 is refused for a flag.
StrictInt = Annotated[int, Strict()]
StrictFloat = Annotated[float, Strict(), Field(allow_inf_nan=False)]
StrictBool = Annotated[bool, Strict()]
StrictDecimal = Annotated[Decimal, BeforeValidator(decimal_input)]


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
