import uuid
from typing import Any

from src.organizations.service import list_organizations


class FakeResult:
    def all(self) -> list[Any]:
        return []


class FakeSession:
    def __init__(self) -> None:
        self.sql = ""

    def execute(self, query: Any) -> FakeResult:
        self.sql = str(query)
        return FakeResult()

    def scalar(self, query: Any) -> int:
        return 0


def run_query(excluded: uuid.UUID | None) -> str:
    session: Any = FakeSession()
    list_organizations(session, None, 20, 0, excluded)
    return str(session.sql)


def test_query_filters_by_owner_only_when_asked() -> None:
    assert "organizations.owner_id !=" in run_query(uuid.uuid7())
    assert "organizations.owner_id !=" not in run_query(None)
