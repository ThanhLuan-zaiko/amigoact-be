from decimal import Decimal
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, ValidationError

from src.posts.schemas import PostCreate
from src.validation import (
    StrictBool,
    StrictDecimal,
    StrictFloat,
    StrictInt,
    decimal_input,
    has_letter,
)


class Numbers(BaseModel):
    count: StrictInt = 0
    ratio: StrictFloat = 0
    flag: StrictBool = False
    hours: Annotated[StrictDecimal, Field(decimal_places=2)] = Decimal(0)


def error_type(**values: object) -> str:
    with pytest.raises(ValidationError) as caught:
        Numbers.model_validate(values)
    return str(caught.value.errors()[0]["type"])


@pytest.mark.parametrize("value", ["5", 5.0, True, "five", None])
def test_integer_refuses_anything_but_an_integer(value: object) -> None:
    assert error_type(count=value) == "int_type"


@pytest.mark.parametrize("value", ["1.5", True, "abc"])
def test_float_refuses_strings_and_flags(value: object) -> None:
    assert error_type(ratio=value) == "float_type"


def test_float_refuses_infinity_and_nan() -> None:
    assert error_type(ratio=float("inf")) == "finite_number"
    assert error_type(ratio=float("nan")) == "finite_number"


@pytest.mark.parametrize("value", ["true", 1, 0, "yes", "on"])
def test_flag_refuses_strings_and_numbers(value: object) -> None:
    assert error_type(flag=value) == "bool_type"


@pytest.mark.parametrize(
    "value", ["1e3", " 2", "2 ", "NaN", "Infinity", "", "1,5", "+1", ".5", True, []]
)
def test_decimal_refuses_anything_but_a_plain_number(value: object) -> None:
    assert error_type(hours=value) == "number_invalid"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2, Decimal(2)), (2.5, Decimal("2.5")), ("2.25", Decimal("2.25")), ("-1", -1)],
)
def test_decimal_accepts_numbers_and_plain_strings(
    value: object, expected: Decimal
) -> None:
    assert Numbers.model_validate({"hours": value}).hours == expected


def test_valid_numbers_pass() -> None:
    model = Numbers.model_validate({"count": 3, "ratio": 2, "flag": True})
    assert (model.count, model.ratio, model.flag) == (3, 2.0, True)


def test_decimal_input_keeps_non_finite_decimals_out() -> None:
    with pytest.raises(ValueError):
        decimal_input(Decimal("NaN"))


@pytest.mark.parametrize("text", ["2024", "!!!", "123-456", "  ", "1.5"])
def test_has_letter_refuses_text_without_a_letter(text: str) -> None:
    with pytest.raises(ValueError):
        has_letter(text)


# "\u0111i" is a Vietnamese word written with an escape, because .py files stay ASCII.
@pytest.mark.parametrize("text", ["Ngay hoi 2024", "Mua he xanh", "A1", "\u0111i"])
def test_has_letter_accepts_text_with_a_letter(text: str) -> None:
    assert has_letter(text) == text


def test_post_title_of_digits_has_its_own_code() -> None:
    with pytest.raises(ValidationError) as caught:
        PostCreate.model_validate({"kind": "discussion", "title": "2024", "body": "x"})
    assert caught.value.errors()[0]["type"] == "text_needs_letter"


def test_post_draft_flag_must_be_a_boolean() -> None:
    with pytest.raises(ValidationError) as caught:
        PostCreate.model_validate(
            {"kind": "discussion", "title": "Hi", "body": "x", "draft": "true"}
        )
    assert caught.value.errors()[0]["type"] == "bool_type"
