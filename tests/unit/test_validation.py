import uuid

import pytest
from pydantic_core import PydanticCustomError

from src.auth.schemas import RegisterRequest
from src.organizations.schemas import (
    OrganizationCreateRequest,
    check_organization_name,
    normalize_website,
)
from src.validation import multi_line, require_uuid7, single_line
from tests.conftest import ORG_FIELDS


def test_single_line_collapses_spaces() -> None:
    assert single_line("  Doan   truong\xa0moi ") == "Doan truong moi"


@pytest.mark.parametrize("text", ["a\x00b", "a\nb", "a\tb", "a\x7fb"])
def test_single_line_rejects_control_characters(text: str) -> None:
    with pytest.raises(PydanticCustomError) as caught:
        single_line(text)
    assert caught.value.type == "text_invalid"


def test_multi_line_keeps_layout_and_normalizes_line_breaks() -> None:
    assert multi_line(" dong 1\r\ndong 2\r\tdong 3 ") == "dong 1\ndong 2\n\tdong 3"


@pytest.mark.parametrize("text", ["a\x00b", "a\x1bb", "a\x7fb"])
def test_multi_line_rejects_other_control_characters(text: str) -> None:
    with pytest.raises(PydanticCustomError) as caught:
        multi_line(text)
    assert caught.value.type == "text_invalid"


def test_require_uuid7_accepts_only_version_7() -> None:
    value = uuid.uuid7()
    assert require_uuid7(value) == value
    for other in (uuid.uuid4(), uuid.uuid1(), uuid.UUID(int=0)):
        with pytest.raises(PydanticCustomError) as caught:
            require_uuid7(other)
        assert caught.value.type == "uuid_invalid"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.org",
        "https://user@example.org",
        "https://localhost",
        "https://exa mple.org",
        "http://[",
        "//example.org",
        "data:text/html,hi",
    ],
)
def test_website_rejects_unsafe_or_broken_urls(url: str) -> None:
    with pytest.raises(PydanticCustomError) as caught:
        normalize_website(url)
    assert caught.value.type == "website_invalid"


def test_website_keeps_a_normal_url_with_path() -> None:
    url = "https://sub.example.vn:8443/gioi-thieu?a=1"
    assert normalize_website(url) == url


@pytest.mark.parametrize("name", ["!!!", "---", "..."])
def test_organization_name_needs_a_letter_or_digit(name: str) -> None:
    with pytest.raises(PydanticCustomError) as caught:
        check_organization_name(name)
    assert caught.value.type == "organization_name_invalid"


def test_organization_name_accepts_vietnamese_letters_and_digits() -> None:
    assert check_organization_name("\u0110o\xe0n 1") == "\u0110o\xe0n 1"
    assert check_organization_name("24") == "24"


def test_organization_request_collapses_spaces_in_the_name() -> None:
    assert (
        OrganizationCreateRequest(**ORG_FIELDS, name=" CLB   Xanh ").name == "CLB Xanh"
    )


def test_account_name_rejects_control_characters() -> None:
    with pytest.raises(ValueError, match="control characters"):
        RegisterRequest(
            email="a@example.com",
            password="Correct-Horse-7-Battery",
            full_name="a\x00b",
        )
