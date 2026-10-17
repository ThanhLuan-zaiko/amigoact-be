"""Migration: chat phase 3 tables (pins + per-user mutes).

Creates org_room_pins and org_room_mutes straight from schemas.cql;
both are additive, CREATE IF NOT EXISTS, safe to re-run.

    uv run python -m migrate.chat_phase3 --dry-run
    uv run python -m migrate.chat_phase3
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.chat_phase3")

TABLES = ("org_room_pins", "org_room_mutes")


def create_tables(session, cfg: common.Config, cql_path) -> dict[str, int]:  # noqa: ANN001, ANN202
    stats = {"created": 0, "skipped": 0}
    for table in TABLES:
        if common.table_exists(session, cfg.keyspace, table):
            stats["skipped"] += 1
            continue
        stmts = common.schema_statements(cql_path, cfg.keyspace, table)
        logger.info(
            "%s: creating table%s.",
            table, " (dry-run)" if cfg.dry_run else "",
        )
        for stmt in stmts:
            if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
                continue
            if not cfg.dry_run:
                session.execute(stmt)
        stats["created"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create org_room_pins and org_room_mutes.", argv
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
        stats = create_tables(session, cfg, common.cql_file(args))
        logger.info(
            "tables: created=%d skipped=%d%s.",
            stats["created"], stats["skipped"],
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
