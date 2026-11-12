from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.models.posts import OrgPost
from src.posts.queries import with_tag


def _compiled(tag: str | None) -> tuple[str, dict[str, object]]:
    compiled = with_tag(select(OrgPost), tag).compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


def test_no_tag_leaves_the_query_alone() -> None:
    query = select(OrgPost)
    assert with_tag(query, None) is query


def test_tag_name_is_matched_by_its_slug() -> None:
    sql, params = _compiled("M\u00f4i Tr\u01b0\u1eddng")
    assert "post_tags" in sql
    assert "deleted_at IS NULL" in sql
    assert "moi-truong" in params.values()


def test_tag_without_letters_or_digits_matches_nothing() -> None:
    sql, params = _compiled("%%")
    assert "false" in sql.lower()
    assert "%%" not in params.values()
