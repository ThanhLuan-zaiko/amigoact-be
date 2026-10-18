"""Migration: multi-pin rooms (chat phase 6).

Adds org_room_pins_v2 (one row per (room_id, message_id)) and backfills
any pins still living in the legacy single-slot org_room_pins table.
Both steps are idempotent; the legacy table is left in place for
rollback and can be dropped manually later.

    uv run python -m migrate.chat_multi_pins --dry-run
    uv run python -m migrate.chat_multi_pins
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.chat_multi_pins")

NEW_TABLE = "org_room_pins_v2"
LEGACY_TABLE = "org_room_pins"


def create_pin_table(session, cfg: common.Config, cql_path) -> None:
    if common.table_exists(session, cfg.keyspace, NEW_TABLE):
        logger.info("%s: table already present.", NEW_TABLE)
        return
    stmts = common.schema_statements(cql_path, cfg.keyspace, NEW_TABLE)
    logger.info(
        "%s: creating table%s.",
        NEW_TABLE, " (dry-run)" if cfg.dry_run else "",
    )
    for stmt in stmts:
        if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
            continue
        if not cfg.dry_run:
            session.execute(stmt)


def backfill_pins(session, cfg: common.Config) -> int:
    """Copy the one legacy pin per room into the v2 table."""
    if not common.table_exists(session, cfg.keyspace, LEGACY_TABLE):
        logger.info("%s: no legacy table; nothing to backfill.",
                    LEGACY_TABLE)
        return 0
    if cfg.dry_run:
        logger.info("%s: would backfill pins into %s (dry-run).",
                    LEGACY_TABLE, NEW_TABLE)
        return 0
    rows = session.execute(
        f"SELECT room_id, message_id, pinned_by, pinned_at "
        f"FROM {cfg.keyspace}.{LEGACY_TABLE}"
    )
    prepared = session.prepare(
        f"INSERT INTO {cfg.keyspace}.{NEW_TABLE} "
        f"(room_id, message_id, pinned_by, pinned_at) "
        f"VALUES (?, ?, ?, ?)"
    )
    count = 0
    for row in rows:
        session.execute(
            prepared,
            (row.room_id, row.message_id, row.pinned_by, row.pinned_at),
        )
        count += 1
    logger.info("%s: backfilled %d pin(s).", LEGACY_TABLE, count)
    return count


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create org_room_pins_v2 and backfill legacy pins.", argv
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
        create_pin_table(session, cfg, common.cql_file(args))
        backfill_pins(session, cfg)
        logger.info("Done%s.", " (dry-run)" if cfg.dry_run else "")
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1
    finally:
        cluster.shutdown()


if __name__ == "__main__":
    sys.exit(main())
