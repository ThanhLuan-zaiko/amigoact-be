"""Migration: chat room sub-threads (chat phase 5).

Adds, all additive and idempotent (re-running is always safe):
- org_chat_channels / org_chat_channels_by_id: parent_room_id (the room
  a thread hangs under) and activity_id (optional linked activity).
- org_chat_room_threads: new table keyed by parent_room_id so one
  room's thread list reads a single partition.

ALTER TABLE ... ADD is guarded by a system_schema.columns probe so a
re-run never fails on already-applied columns.

    uv run python -m migrate.chat_threads --dry-run
    uv run python -m migrate.chat_threads
"""

from __future__ import annotations

import logging
import sys

from migrate import common
from migrate.chat_phase2 import column_exists

logger = logging.getLogger("migrate.chat_threads")

THREAD_TABLE = "org_chat_room_threads"

# (table, [(column, cql_type)]) - every entry is one ALTER ... ADD.
NEW_COLUMNS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "org_chat_channels",
        [("parent_room_id", "uuid"), ("activity_id", "uuid")],
    ),
    (
        "org_chat_channels_by_id",
        [("parent_room_id", "uuid"), ("activity_id", "uuid")],
    ),
]


def add_columns(session, cfg: common.Config) -> dict[str, int]:
    stats = {"added": 0, "skipped": 0}
    for table, columns in NEW_COLUMNS:
        if not common.table_exists(session, cfg.keyspace, table):
            logger.warning("%s missing; skipping its columns.", table)
            continue
        for column, cql_type in columns:
            if column_exists(session, cfg.keyspace, table, column):
                stats["skipped"] += 1
                continue
            stmt = (
                f"ALTER TABLE {cfg.keyspace}.{table} "
                f"ADD {column} {cql_type}"
            )
            logger.info(
                "%s.%s: ADD %s %s%s.",
                table, column, column, cql_type,
                " (dry-run)" if cfg.dry_run else "",
            )
            if not cfg.dry_run:
                session.execute(stmt)
            stats["added"] += 1
    return stats


def create_thread_table(
    session, cfg: common.Config, cql_path  # noqa: ANN001
) -> None:
    if common.table_exists(session, cfg.keyspace, THREAD_TABLE):
        logger.info("%s: table already present.", THREAD_TABLE)
        return
    stmts = common.schema_statements(cql_path, cfg.keyspace, THREAD_TABLE)
    logger.info(
        "%s: creating table%s.",
        THREAD_TABLE, " (dry-run)" if cfg.dry_run else "",
    )
    for stmt in stmts:
        if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
            continue
        if not cfg.dry_run:
            session.execute(stmt)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Add thread columns and the org_chat_room_threads table.", argv
    )
    try:
        cfg = common.resolve_config(args)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2
    logger.info(
        "Target keyspace '%s' at %s:%d.",
        cfg.keyspace, ",".join(cfg.hosts), cfg.port,
    )
    logger.info("ScyllaDB probe: %s.", common.probe(cfg))
    try:
        cluster, session = common.connect(cfg)
    except Exception as exc:
        logger.error("Cannot reach ScyllaDB: %s", exc)
        return 1
    try:
        stats = add_columns(session, cfg)
        create_thread_table(session, cfg, common.cql_file(args))
        logger.info(
            "columns: added=%d skipped=%d (already present)%s.",
            stats["added"], stats["skipped"],
            " (dry-run)" if cfg.dry_run else "",
        )
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1
    finally:
        cluster.shutdown()


if __name__ == "__main__":
    sys.exit(main())
