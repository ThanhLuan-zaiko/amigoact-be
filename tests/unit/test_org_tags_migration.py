"""Unit tests: migrate.org_tags dry-run never touches the new tables."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
import uuid_utils

from migrate import org_tags

NOW = datetime.now(UTC)


class _FakeResult:
    def __init__(self, rows: list):
        self._rows = rows

    def __iter__(self):  # noqa: ANN204
        return iter(self._rows)

    def one(self):  # noqa: ANN202
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Records every statement; serves only the activities page."""

    def __init__(self, rows: list) -> None:
        self.rows = rows
        self.statements: list[str] = []

    def execute(self, statement, parameters=None):  # noqa: ANN001, ANN202
        text = getattr(statement, "query_string", str(statement))
        self.statements.append(text)
        return _FakeResult(self.rows)


def _activity(org_id: UUID, slug_bit: str, names: list[str]):
    return SimpleNamespace(
        id=uuid_utils.uuid7(), org_id=org_id, slug=slug_bit,
        tag_names=names, created_at=NOW,
    )


def test_dry_run_never_reads_or_writes_the_new_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_a, org_b = uuid_utils.uuid7(), uuid_utils.uuid7()
    rows = [
        _activity(org_a, "a1", ["Alpha", "Beta"]),
        _activity(org_a, "a2", ["Alpha"]),  # shared slug in one org
        _activity(org_b, "b1", ["Gamma"]),
        _activity(org_b, "b2", []),  # untagged rows are skipped
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(
        org_tags.common, "table_exists", lambda *a: False
    )
    monkeypatch.setattr(
        org_tags.common,
        "schema_statements",
        lambda *a: ["CREATE TABLE IF NOT EXISTS stub (id uuid PRIMARY KEY)"],
    )

    stats = org_tags.run(session, "ks", dry_run=True)

    assert stats == {
        "activities": 3,
        "catalog_created": 3,
        "edges": 4,
        "directory": 4,
    }
    assert len(session.statements) == 1
    assert "activities" in session.statements[0]
    forbidden = (
        "tags_by_org",
        "activity_tags_by_org",
        "trashed_tag_edges_by_org",
        "public_tag_directory",
    )
    assert not any(
        table in stmt
        for stmt in session.statements
        for table in forbidden
    )
