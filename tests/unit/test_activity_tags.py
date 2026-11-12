import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.activities.schemas import ActivityUpdateRequest
from src.activities.tags import with_activity_tag
from src.models.activities import Activity


def _compiled(tag: str | None) -> tuple[str, dict[str, object]]:
    query = with_activity_tag(select(Activity), tag)
    compiled = query.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


def test_no_tag_leaves_the_query_alone() -> None:
    query = select(Activity)
    assert with_activity_tag(query, None) is query


def test_tag_name_is_matched_by_its_slug() -> None:
    sql, params = _compiled("M\u00f4i Tr\u01b0\u1eddng")
    assert "activity_tags" in sql
    assert "moi-truong" in params.values()


def test_tag_without_letters_matches_nothing() -> None:
    sql, _ = _compiled("%%")
    assert "false" in sql.lower()


def test_activity_takes_at_most_five_tags() -> None:
    ActivityUpdateRequest(tags=["a", "b", "c", "d", "e"])
    with pytest.raises(ValidationError):
        ActivityUpdateRequest(tags=["a", "b", "c", "d", "e", "f"])


def test_tag_names_are_single_line_and_short() -> None:
    with pytest.raises(ValidationError):
        ActivityUpdateRequest(tags=["a\nb"])
    with pytest.raises(ValidationError):
        ActivityUpdateRequest(tags=["a" * 41])


def test_leaving_tags_out_keeps_them() -> None:
    assert ActivityUpdateRequest(title="Moi").tags is None
