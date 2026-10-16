"""Durable primitives: idempotency keys + job leases (schemas.cql section 14).

Both stores use raw CQL like CqlRateLimiter: idempotency claims need
INSERT ... IF NOT EXISTS and lease takeover needs conditional UPDATE,
neither of which cqlengine models express cleanly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from core.security import utcnow

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
LEASE_TTL_SECONDS = 5 * 60


class IdempotencyStore(ABC):
    """Client-supplied key -> stored response for safe replays."""

    @abstractmethod
    def claim(self, key: str, user_id: UUID | None, now: datetime) -> str | None:
        """INSERT IF NOT EXISTS. Returns stored response_json when the key
        already completed, "in_progress" while another request runs, else
        None when the caller now owns the key."""

    @abstractmethod
    def complete(self, key: str, response_json: str, now: datetime) -> None:
        """Mark the key completed with the replayable response payload."""

    @abstractmethod
    def fail(self, key: str, now: datetime) -> None:
        """Mark the key failed so a retry may claim it again."""


class JobLeaseStore(ABC):
    """Single-worker lease on a background job row."""

    @abstractmethod
    def acquire(self, job_id: UUID, owner: str, ttl_seconds: int) -> bool:
        """Take or renew the lease; False when another live owner holds it."""

    @abstractmethod
    def release(self, job_id: UUID, owner: str, status: str) -> None:
        """Mark the lease 'done' or hand it back as 'free'."""


class CqlIdempotencyStore(IdempotencyStore):
    """idempotency_keys rows with a 24h TTL; LWT claim avoids double-runs."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def claim(self, key: str, user_id: UUID | None, now: datetime) -> str | None:
        session = get_session()
        expires = now + timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)
        applied = session.execute(
            f"INSERT INTO {self._keyspace}.idempotency_keys "
            "(key, user_id, status, response_json, created_at, expires_at) "
            "VALUES (%s, %s, 'in_progress', NULL, %s, %s) "
            "IF NOT EXISTS USING TTL %s",
            (key, user_id, now, expires, IDEMPOTENCY_TTL_SECONDS),
        ).one()
        if applied and applied.applied:
            return None
        row = session.execute(
            f"SELECT status, response_json, expires_at "
            f"FROM {self._keyspace}.idempotency_keys WHERE key = %s",
            (key,),
        ).one()
        if row is None:
            return None
        if row.status == "completed" and not _past(row.expires_at):
            return row.response_json or ""
        if row.status == "failed" or _past(row.expires_at):
            # Previous attempt failed or rotted: reclaim for this retry.
            session.execute(
                f"UPDATE {self._keyspace}.idempotency_keys USING TTL %s "
                "SET status = 'in_progress', user_id = %s, created_at = %s, "
                "expires_at = %s WHERE key = %s",
                (IDEMPOTENCY_TTL_SECONDS, user_id, now, expires, key),
            )
            return None
        return "in_progress"

    def complete(self, key: str, response_json: str, now: datetime) -> None:
        get_session().execute(
            f"UPDATE {self._keyspace}.idempotency_keys "
            "SET status = 'completed', response_json = %s WHERE key = %s",
            (response_json, key),
        )

    def fail(self, key: str, now: datetime) -> None:
        get_session().execute(
            f"UPDATE {self._keyspace}.idempotency_keys "
            "SET status = 'failed' WHERE key = %s",
            (key,),
        )


class CqlJobLeaseStore(JobLeaseStore):
    """job_leases rows; takeover allowed only after expires_at passes."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def acquire(self, job_id: UUID, owner: str, ttl_seconds: int) -> bool:
        session = get_session()
        now = utcnow()
        expires = now + timedelta(seconds=ttl_seconds)
        applied = session.execute(
            f"INSERT INTO {self._keyspace}.job_leases "
            "(job_id, owner, status, acquired_at, expires_at) "
            "VALUES (%s, %s, 'held', %s, %s) IF NOT EXISTS",
            (job_id, owner, now, expires),
        ).one()
        if applied and applied.applied:
            return True
        row = session.execute(
            f"SELECT owner, status, expires_at "
            f"FROM {self._keyspace}.job_leases WHERE job_id = %s",
            (job_id,),
        ).one()
        if row is None:
            return True
        if row.status == "done":
            return False
        if row.owner == owner or _past(row.expires_at):
            session.execute(
                f"UPDATE {self._keyspace}.job_leases SET owner = %s, "
                "status = 'held', acquired_at = %s, expires_at = %s "
                "WHERE job_id = %s",
                (owner, now, expires, job_id),
            )
            return True
        return False

    def release(self, job_id: UUID, owner: str, status: str) -> None:
        get_session().execute(
            f"UPDATE {self._keyspace}.job_leases SET status = %s, "
            "expires_at = %s WHERE job_id = %s IF owner = %s",
            (status, utcnow(), job_id, owner),
        )


def _past(moment: datetime | None) -> bool:
    return moment is None or moment <= utcnow()
