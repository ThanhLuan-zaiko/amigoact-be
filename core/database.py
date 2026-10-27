"""Read-only ScyllaDB connectivity check used at application startup."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass


@dataclass(frozen=True)
class ScyllaStatus:
    """Outcome of one startup connectivity probe (never raises)."""

    ok: bool
    cluster_name: str = ""
    release_version: str = ""
    tables: int = -1
    error: str = ""


def _ensure_reactor_compat() -> None:
    """Seed the expected asyncore reactor with the asyncio implementation.

    The driver probes gevent/eventlet/libev/asyncore at import time and
    raises DependencyException when none load. Python 3.12 removed the
    stdlib asyncore module, so map the expected attribute to the bundled
    AsyncioConnection before cassandra.cluster is imported anywhere.
    """
    try:
        from cassandra.io import asyncorereactor  # noqa: F401

        return
    except Exception:
        pass
    try:
        from cassandra.io.asyncioreactor import AsyncioConnection
    except Exception:
        return
    alias = types.ModuleType("cassandra.io.asyncorereactor")
    alias.AsyncoreConnection = AsyncioConnection
    sys.modules["cassandra.io.asyncorereactor"] = alias


_ensure_reactor_compat()


# Generous client-side limits: a local ScyllaDB in Docker/WSL2 can stall for
# several seconds (Raft, compaction, schema changes) without being down.
CONNECT_TIMEOUT = 15.0
REQUEST_TIMEOUT = 30.0
DDL_TIMEOUT = 120.0


def cluster_options(
    connect_timeout: float = CONNECT_TIMEOUT,
    request_timeout: float = REQUEST_TIMEOUT,
    local_dc: str = "",
    username: str = "",
    password: str = "",
) -> dict[str, object]:
    """Shared Cluster kwargs: longer timeouts, retries, auto-reconnect."""
    from cassandra import ConsistencyLevel
    from cassandra.cluster import EXEC_PROFILE_DEFAULT, ExecutionProfile
    from cassandra.io.asyncioreactor import AsyncioConnection
    from cassandra.policies import (
        DCAwareRoundRobinPolicy,
        ExponentialReconnectionPolicy,
        RetryPolicy,
        RoundRobinPolicy,
        TokenAwarePolicy,
    )

    child = (
        DCAwareRoundRobinPolicy(local_dc=local_dc)
        if local_dc
        else RoundRobinPolicy()
    )
    profile = ExecutionProfile(
        load_balancing_policy=TokenAwarePolicy(child),
        retry_policy=RetryPolicy(),
        request_timeout=request_timeout,
        # LWT Paxos/Raft round stays inside the local DC.
        serial_consistency_level=ConsistencyLevel.LOCAL_SERIAL,
    )
    options: dict[str, object] = {
        "connection_class": AsyncioConnection,
        # ScyllaDB speaks protocol v4 max; pin it to skip noisy downgrades.
        "protocol_version": 4,
        "connect_timeout": connect_timeout,
        "control_connection_timeout": connect_timeout,
        "execution_profiles": {EXEC_PROFILE_DEFAULT: profile},
        "reconnection_policy": ExponentialReconnectionPolicy(1.0, 30.0),
        # Keep idle sockets alive so WSL2/NAT does not silently drop them.
        "idle_heartbeat_interval": 15,
        "idle_heartbeat_timeout": 30,
        "max_schema_agreement_wait": 60,
    }
    if username:
        from cassandra.auth import PlainTextAuthProvider

        options["auth_provider"] = PlainTextAuthProvider(
            username=username, password=password
        )
    return options


def execute_with_retry(session, statement, params=None, *, attempts: int = 3,
                       timeout: float | None = None):
    """Run an idempotent statement, retrying transient client/host errors."""
    import time

    from cassandra import OperationTimedOut
    from cassandra.cluster import _NOT_SET, NoHostAvailable

    # None would mean "wait forever" to the driver; keep the profile default.
    limit = _NOT_SET if timeout is None else timeout
    for attempt in range(1, attempts + 1):
        try:
            return session.execute(statement, params, timeout=limit)
        except (OperationTimedOut, NoHostAvailable):
            if attempt == attempts:
                raise
            time.sleep(2.0 * attempt)
    return None


def connect(
    hosts: list[str],
    keyspace: str,
    local_dc: str = "",
    *,
    port: int = 9042,
    username: str = "",
    password: str = "",
    connect_timeout: float = CONNECT_TIMEOUT,
    request_timeout: float = REQUEST_TIMEOUT,
) -> None:
    """Register the single cqlengine connection for repository access."""
    from cassandra.cqlengine import connection

    options = cluster_options(
        connect_timeout, request_timeout, local_dc, username, password
    )
    connection.setup(hosts, keyspace, port=port, **options)


def _load_cluster_class() -> object | None:
    """Import Cluster, aliasing the asyncio reactor when C extensions miss."""
    try:
        from cassandra.cluster import Cluster

        return Cluster
    except ImportError:
        return None
    except Exception:
        pass
    try:
        from cassandra.io.asyncioreactor import AsyncioConnection as AsyncConn

        alias = types.ModuleType("cassandra.io.asyncorereactor")
        alias.AsyncoreConnection = AsyncConn
        sys.modules["cassandra.io.asyncorereactor"] = alias
        from cassandra.cluster import Cluster

        return Cluster
    except Exception:
        return None


def check_scylla_connection(
    hosts: list[str],
    port: int,
    keyspace: str,
    timeout: float = CONNECT_TIMEOUT,
    local_dc: str = "",
    username: str = "",
    password: str = "",
) -> ScyllaStatus:
    """Connect, read cluster metadata and count tables. Read-only, no writes."""
    cluster_cls = _load_cluster_class()
    if cluster_cls is None:
        return ScyllaStatus(ok=False, error="cassandra-driver is not installed")
    try:
        options = cluster_options(
            connect_timeout=timeout,
            local_dc=local_dc,
            username=username,
            password=password,
        )
        cluster = cluster_cls(hosts, port=port, **options)
        session = cluster.connect()
    except Exception as exc:
        return ScyllaStatus(ok=False, error=str(exc)[:300])
    try:
        row = session.execute(
            "SELECT cluster_name, release_version FROM system.local"
        ).one()
        tables = sum(
            1
            for _ in session.execute(
                "SELECT table_name FROM system_schema.tables"
                " WHERE keyspace_name = %s",
                [keyspace],
            )
        )
        return ScyllaStatus(
            ok=True,
            cluster_name=row.cluster_name if row else "",
            release_version=row.release_version if row else "",
            tables=tables,
        )
    except Exception as exc:
        return ScyllaStatus(ok=False, error=str(exc)[:300])
    finally:
        cluster.shutdown()
