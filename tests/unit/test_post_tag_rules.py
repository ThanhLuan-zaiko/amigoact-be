"""Unit tests: the 3-tag slice applied before a post claims names."""

from __future__ import annotations

from posts.tag_rules import dedupe_tag_names, take_post_tags


def test_take_post_tags_keeps_the_first_three_nonempty() -> None:
    names = take_post_tags(["  A ", "", "B", "  ", "C", "D"])
    assert names == ["A", "B", "C"]


def test_take_post_tags_ignores_missing_and_non_strings() -> None:
    assert take_post_tags(None) == []
    assert take_post_tags(["", "   "]) == []


def test_dedupe_tag_names_drops_a_later_slug() -> None:
    names = dedupe_tag_names(["Hoc bong", "Y te", "HOC BONG", ""])
    assert names == ["Hoc bong", "Y te"]
