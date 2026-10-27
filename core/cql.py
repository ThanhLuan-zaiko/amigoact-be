"""Raw CQL helpers: prepared-statement cache, safe LWT claims, TTL cache.

Repositories keep writing `%s` placeholders; `run` converts them to `?`
and prepares each distinct query once per session, so the server skips
re-parsing and the driver can route token-aware to the owning replica.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, Generic, TypeVar

logger = logging.getLogger("amigoact.cql")

T = TypeVar("T")

_prepared: dict[tuple[int, str], Any] = {}
_prepared_lock = threading.Lock()


def _session() -> Any:
    from cassandra.cqlengine.connection import get_session

    return get_session()


def prepare(session: Any, cql: str) -> Any:
    """Return the cached PreparedStatement for `cql` on this session."""
    key = (id(session), cql)
    statement = _prepared.get(key)
    if statement is None:
        with _prepared_lock:
            statement = _prepared.get(key)
            if statement is None:
                statement = session.prepare(cql.replace("%s", "?"))
                _prepared[key] = statement
    return statement


def run(cql: str, params: Sequence[Any] = (), session: Any = None) -> Any:
    """Execute `cql` as a prepared statement on the cqlengine session."""
    active = session if session is not None else _session()
    return active.execute(prepare(active, cql), list(params))


def _transient() -> tuple[type[BaseException], ...]:
    from cassandra import OperationTimedOut, WriteTimeout
    from cassandra.cluster import NoHostAvailable

    return (OperationTimedOut, WriteTimeout, NoHostAvailable)


def claim(
    cql: str,
    params: Sequence[Any],
    owned: Callable[[], bool],
    attempts: int = 3,
) -> bool:
    """Run an `IF NOT EXISTS` claim; True when this caller owns the row.

    A timed-out LWT has an unknown outcome (it may have been applied), so
    blind retries would report a false conflict. After each transient error
    `owned()` re-reads the row: ours means success, otherwise try again.
    """
    errors = _transient()
    for attempt in range(1, attempts + 1):
        try:
            return bool(run(cql, params).was_applied)
        except errors as exc:
            logger.warning("LWT claim attempt %d failed: %s", attempt, exc)
            try:
                if owned():
                    return True
            except errors:
                pass
            if attempt == attempts:
                raise
            time.sleep(0.2 * 2**attempt)
    return False


class TtlCache(Generic[T]):
    """Tiny process-local cache for hot, rarely changing reads."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._items: dict[Any, tuple[float, T]] = {}
        self._generation = 0

    def get_or_load(self, key: Any, load: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]
            generation = self._generation
        value = load()
        with self._lock:
            # A clear() during the load means the value may be stale.
            if generation == self._generation:
                self._items[key] = (time.monotonic() + self._ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._items.clear()
