"""The home feed rules: visitors see public posts, members also see their organizations."""

import uuid

from sqlalchemy.dialects import postgresql

from src.posts.visibility import visible_to


def _sql(clause: object) -> str:
    return str(clause.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


def test_visitors_only_match_public_posts() -> None:
    text = _sql(visible_to(None))

    assert "visibility" in text
    assert " IN " not in text


def test_members_also_match_posts_of_their_organizations() -> None:
    text = _sql(visible_to(uuid.uuid4()))

    assert "visibility" in text
    assert " IN " in text
