"""Unit tests: migrate.user_tags copies live org tags and leaves org rows."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import uuid_utils

from migrate.user_tags import copy_owned

NOW = datetime.now(UTC)
OWNER = UUID("00000000-0000-7000-8000-000000000001")
AUTHOR = UUID("00000000-0000-7000-8000-000000000002")
ORG = UUID("00000000-0000-7000-8000-000000000010")
OTHER = UUID("00000000-0000-7000-8000-000000000011")


def _org(org_id: UUID, owner: UUID, deleted: bool = False):
    return SimpleNamespace(
        id=org_id, owner_id=owner, deleted_at=NOW if deleted else None,
    )


def _tag(org_id: UUID, slug: str, name: str, deleted: bool = False):
    return SimpleNamespace(
        org_id=org_id, slug=slug, name=name,
        created_at=NOW, updated_at=NOW,
        deleted_at=NOW if deleted else None,
    )


def _post(org_id: UUID, names: list[str], **flags: object):
    return SimpleNamespace(
        post_id=uuid_utils.uuid7(), org_id=org_id, author_id=AUTHOR,
        tag_names=names,
        deleted_at=NOW if flags.get("deleted") else None,
        revision_of=uuid_utils.uuid7() if flags.get("revision") else None,
    )


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def __iter__(self):  # noqa: ANN204
        return iter(self._rows)

    def one(self):  # noqa: ANN202
        return self._rows[0] if self._rows else None


class _Session:
    """Serves the three scans and records personal-catalog writes."""

    def __init__(
        self, orgs: list, tags: list, posts: list, held: set[tuple] | None = None,
    ) -> None:
        self.orgs = orgs
        self.tags = tags
        self.posts = posts
        self.held = held or set()
        self.writes: list[tuple[str, list]] = []

    def execute(self, statement, parameters=None):  # noqa: ANN001, ANN202
        text = getattr(statement, "query_string", str(statement))
        params = list(parameters or [])
        upper = text.upper()
        if upper.startswith("INSERT") or upper.startswith("UPDATE"):
            self.writes.append((text, params))
            if "TAGS_BY_USER" in upper:
                self.held.add((params[0], params[1]))
            return _Result([])
        if "ORGANIZATIONS" in upper:
            return _Result(self.orgs)
        if "TAGS_BY_ORG" in upper:
            return _Result(self.tags)
        if "ORG_POSTS" in upper:
            return _Result(self.posts)
        if "POST_TAGS_BY_USER" in upper or "USER_POST_TAG_SETS" in upper:
            return _Result([])
        if "TAGS_BY_USER" in upper:
            key = (params[0], params[1])
            row = SimpleNamespace(name="kept") if key in self.held else None
            return _Result([row] if row else [])
        raise AssertionError(text)


def test_copy_keeps_one_spelling_and_skips_trash() -> None:
    session = _Session(
        [_org(ORG, OWNER), _org(OTHER, OWNER)],
        [
            _tag(ORG, "mua-he", "Mua he"),
            _tag(OTHER, "mua-he", "MUA HE"),
            _tag(ORG, "cu", "Cu", deleted=True),
        ],
        [],
    )

    stats = copy_owned(session, "ks", dry_run=False)

    assert stats["tags_copied"] == 1
    assert stats["tags_kept"] == 0
    inserts = [params for text, params in session.writes if "INSERT" in text]
    assert inserts == [[OWNER, "mua-he", "Mua he", NOW, NOW]]


def test_existing_personal_slug_is_not_rewritten() -> None:
    session = _Session(
        [_org(ORG, OWNER)],
        [_tag(ORG, "mua-he", "Mua he")],
        [],
        held={(OWNER, "mua-he")},
    )

    stats = copy_owned(session, "ks", dry_run=False)

    assert stats == {"tags_copied": 0, "tags_kept": 1, "edges": 0, "sets": 0}
    assert session.writes == []


def test_live_post_is_bound_for_owner_and_author() -> None:
    live = _post(ORG, ["Mua he", "Mua he", "Khac"])
    session = _Session(
        [_org(ORG, OWNER)],
        [_tag(ORG, "mua-he", "Mua he")],
        [
            live,
            _post(ORG, ["Mua he"], deleted=True),
            _post(ORG, ["Mua he"], revision=True),
        ],
    )

    stats = copy_owned(session, "ks", dry_run=False)

    # Catalog spelling for the owner, plus the post-only name, for both people.
    assert stats["tags_copied"] == 4
    assert stats["edges"] == 4
    assert stats["sets"] == 2
    edge_users = {
        params[0] for text, params in session.writes if "post_tags_by_user" in text
    }
    assert edge_users == {OWNER, AUTHOR}
    owner_edges = [
        params for text, params in session.writes
        if "post_tags_by_user" in text and params[0] == OWNER
    ]
    assert [params[1] for params in owner_edges] == ["mua-he", "khac"]
    assert all(params[2] == live.post_id for params in owner_edges)


def test_dry_run_writes_nothing() -> None:
    session = _Session(
        [_org(ORG, OWNER)],
        [_tag(ORG, "mua-he", "Mua he")],
        [_post(ORG, ["Mua he"])],
    )

    stats = copy_owned(session, "ks", dry_run=True)

    assert stats["tags_copied"] == 2
    assert stats["edges"] == 2
    assert session.writes == []
