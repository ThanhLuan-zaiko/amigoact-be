"""Unit tests for core.cql: prepared cache, safe LWT claim, TTL cache."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cassandra import OperationTimedOut

from core import cql
from core.cql import TtlCache, claim, prepare, run


class FakeSession:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.prepared: list[str] = []
        self.calls: list[tuple[object, list[object]]] = []
        self._outcomes = list(outcomes or [])

    def prepare(self, query: str) -> str:
        self.prepared.append(query)
        return f"prepared:{query}"

    def execute(self, statement: object, params: list[object]) -> object:
        self.calls.append((statement, params))
        outcome = self._outcomes.pop(0) if self._outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cql, "_prepared", {})
    monkeypatch.setattr(cql.time, "sleep", lambda _s: None)


def test_prepare_converts_placeholders_once() -> None:
    session = FakeSession()
    first = prepare(session, "SELECT * FROM t WHERE a = %s AND b = %s")
    second = prepare(session, "SELECT * FROM t WHERE a = %s AND b = %s")
    assert first == second
    assert session.prepared == ["SELECT * FROM t WHERE a = ? AND b = ?"]


def test_run_executes_prepared_with_list_params() -> None:
    session = FakeSession(["row"])
    assert run("SELECT x FROM t WHERE k = %s", ("key",), session=session) == "row"
    assert session.calls == [("prepared:SELECT x FROM t WHERE k = ?", ["key"])]


def _patch_session(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> None:
    monkeypatch.setattr(cql, "_session", lambda: session)


def test_claim_returns_was_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession([SimpleNamespace(was_applied=False)])
    _patch_session(monkeypatch, session)
    assert claim("INSERT %s IF NOT EXISTS", [1], lambda: True) is False


def test_claim_timeout_but_row_is_ours_counts_as_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession([OperationTimedOut("slow")])
    _patch_session(monkeypatch, session)
    assert claim("INSERT %s IF NOT EXISTS", [1], lambda: True) is True
    assert len(session.calls) == 1


def test_claim_retries_when_row_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession(
        [OperationTimedOut("slow"), SimpleNamespace(was_applied=True)]
    )
    _patch_session(monkeypatch, session)
    assert claim("INSERT %s IF NOT EXISTS", [1], lambda: False) is True
    assert len(session.calls) == 2


def test_claim_raises_after_last_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession([OperationTimedOut("slow")] * 3)
    _patch_session(monkeypatch, session)
    with pytest.raises(OperationTimedOut):
        claim("INSERT %s IF NOT EXISTS", [1], lambda: False)
    assert len(session.calls) == 3


def test_ttl_cache_hits_until_cleared() -> None:
    cache: TtlCache[int] = TtlCache(ttl_seconds=60)
    loads: list[int] = []

    def load() -> int:
        loads.append(1)
        return len(loads)

    assert cache.get_or_load("k", load) == 1
    assert cache.get_or_load("k", load) == 1
    cache.clear()
    assert cache.get_or_load("k", load) == 2


def test_ttl_cache_skips_store_when_cleared_during_load() -> None:
    cache: TtlCache[str] = TtlCache(ttl_seconds=60)

    def stale_load() -> str:
        cache.clear()  # a write lands while this read is in flight
        return "stale"

    assert cache.get_or_load("k", stale_load) == "stale"
    assert cache.get_or_load("k", lambda: "fresh") == "fresh"


def test_ttl_cache_expires() -> None:
    cache: TtlCache[str] = TtlCache(ttl_seconds=0)
    cache.get_or_load("k", lambda: "old")
    assert cache.get_or_load("k", lambda: "new") == "new"
