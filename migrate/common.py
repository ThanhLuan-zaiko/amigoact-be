"""Shared plumbing for migrate/ scripts: flags, config, session, DDL.

Migration modules call `parse_args` + `resolve_config` + `connect`,
apply their own statements, then log counters. Nothing here drops or
truncates data; migrations must stay idempotent (IF NOT EXISTS DDL and
upsert-style writes) so re-running is always safe.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import types
from dataclasses import dataclass

from reset_db import (
    DEFAULT_ENV,
    DEFAULT_KEYSPACE,
    DEFAULT_PORT,
    detect_scylla,
    load_dotenv,
    load_statements,
    resolve_path,
    split_hosts,
)

FETCH_SIZE = 500


@dataclass
class Config:
    """Resolved connection settings from .env plus CLI overrides."""

    hosts: list[str]
    port: int
    keyspace: str
    username: str
    password: str
    datacenter: str
    timeout: float
    dry_run: bool


def parse_args(description: str, argv: list[str] | None = None):
    """Standard migration flags; pass the module's own description."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--env", default=DEFAULT_ENV, help="Path to .env.")
    parser.add_argument("--cql", default="schemas.cql", help="Schema file.")
    parser.add_argument("--hosts", default="", help="Comma-separated hosts.")
    parser.add_argument("--port", type=int, default=0, help="CQL port.")
    parser.add_argument("--keyspace", default="", help="Target keyspace.")
    parser.add_argument("--username", default="", help="CQL username.")
    parser.add_argument("--password", default="", help="CQL password.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count rows and print DDL; write nothing.",
    )
    return parser.parse_args(argv)


def resolve_config(args) -> Config:
    """Merge .env values with CLI flags into one Config."""
    env_path = resolve_path(args.env)
    cql_path = resolve_path(args.cql)
    if not cql_path.is_file():
        raise RuntimeError(f"CQL file not found: {cql_path}")
    config = load_dotenv(env_path)
    return Config(
        hosts=split_hosts(args.hosts or config.get("SCYLLA_HOSTS", "")),
        port=args.port or int(config.get("SCYLLA_PORT", str(DEFAULT_PORT))),
        keyspace=args.keyspace
        or config.get("SCYLLA_KEYSPACE", DEFAULT_KEYSPACE),
        username=args.username or config.get("SCYLLA_USERNAME", ""),
        password=args.password or config.get("SCYLLA_PASSWORD", ""),
        datacenter=config.get("SCYLLA_DATACENTER", "datacenter1"),
        timeout=args.timeout,
        dry_run=args.dry_run,
    )


def cql_file(args) -> pathlib.Path:
    return resolve_path(args.cql)


def probe(cfg: Config) -> str:
    return detect_scylla(cfg.hosts, cfg.port, cfg.timeout)


def connect(cfg: Config):
    """Plain-driver session; mirrors reset_db's reactor/protocol setup."""
    try:
        from cassandra.cluster import Cluster
    except Exception:
        from cassandra.io.asyncioreactor import (
            AsyncioConnection as AsyncConn,
        )

        alias = types.ModuleType("cassandra.io.asyncorereactor")
        alias.AsyncoreConnection = AsyncConn
        sys.modules["cassandra.io.asyncorereactor"] = alias
        from cassandra.cluster import Cluster
    from cassandra.io.asyncioreactor import AsyncioConnection

    options: dict[str, object] = {
        "connect_timeout": cfg.timeout,
        "connection_class": AsyncioConnection,
        "protocol_version": 4,  # ScyllaDB max is v4.
    }
    if cfg.datacenter:
        from cassandra.policies import DCAwareRoundRobinPolicy

        options["load_balancing_policy"] = DCAwareRoundRobinPolicy(
            local_dc=cfg.datacenter
        )
    if cfg.username:
        from cassandra.auth import PlainTextAuthProvider

        options["auth_provider"] = PlainTextAuthProvider(
            username=cfg.username, password=cfg.password
        )
    cluster = Cluster(cfg.hosts, port=cfg.port, **options)  # type: ignore[arg-type]
    return cluster, cluster.connect()


def schema_statements(
    cql_path: pathlib.Path, keyspace: str, table: str
) -> list[str]:
    """DDL for one table: CREATE KEYSPACE + USE + its CREATE TABLE."""
    statements, _ = load_statements(cql_path, keyspace)
    prefix = ("CREATE KEYSPACE", "USE")
    target = f"CREATE TABLE IF NOT EXISTS {table.upper()}"
    wanted = [
        stmt
        for stmt in statements
        if stmt.upper().startswith(prefix) or stmt.upper().startswith(target)
    ]
    if not any(table in stmt for stmt in wanted):
        raise RuntimeError(f"No CREATE TABLE for {table} in {cql_path}")
    return wanted


def table_exists(session, keyspace: str, table: str) -> bool:
    row = session.execute(
        "SELECT table_name FROM system_schema.tables "
        "WHERE keyspace_name = %s AND table_name = %s",
        [keyspace, table],
    ).one()
    return row is not None
