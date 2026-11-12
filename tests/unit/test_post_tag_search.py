import pytest
from pydantic import ValidationError

from src.posts.rules import tag_slug, tag_word_patterns
from src.posts.schemas import TagSuggestion


def test_patterns_match_the_first_word_or_any_later_word() -> None:
    assert tag_word_patterns("truong") == ("truong%", "%-truong%")


@pytest.mark.parametrize(
    ("typed", "prefix"),
    [
        ("M\u00f4i tr", "moi-tr"),
        ("  \u0110o\u00e0n ", "doan"),
        ("HIEN", "hien"),
    ],
)
def test_typed_text_becomes_the_same_prefix_as_a_slug(typed: str, prefix: str) -> None:
    assert tag_slug(typed) == prefix


def test_prefix_from_tag_slug_has_no_like_wildcards() -> None:
    prefix = tag_slug("50% _off\\")
    assert prefix is not None
    assert not set("%_\\") & set(prefix)


def test_suggestion_needs_name_slug_and_count() -> None:
    item = TagSuggestion(name="M\u00f4i tr\u01b0\u1eddng", slug="moi-truong", count=2)
    assert item.model_dump() == {
        "name": "M\u00f4i tr\u01b0\u1eddng",
        "slug": "moi-truong",
        "count": 2,
    }
    with pytest.raises(ValidationError):
        TagSuggestion.model_validate({"name": "x", "slug": "x"})
