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
    timeout: float = 10.0,
    local_dc: str = "",
) -> ScyllaStatus:
    """Connect, read cluster metadata and count tables. Read-only, no writes."""
    cluster_cls = _load_cluster_class()
    if cluster_cls is None:
        return ScyllaStatus(ok=False, error="cassandra-driver is not installed")
    try:
        from cassandra.io.asyncioreactor import AsyncioConnection
        from cassandra.policies import DCAwareRoundRobinPolicy

        options: dict[str, object] = {
            "connect_timeout": timeout,
            "connection_class": AsyncioConnection,
            # ScyllaDB speaks protocol v4 max; pin it to skip noisy downgrades.
            "protocol_version": 4,
        }
        if local_dc:
            options["load_balancing_policy"] = DCAwareRoundRobinPolicy(
                local_dc=local_dc
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
