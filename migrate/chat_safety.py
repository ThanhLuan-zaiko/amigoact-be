"""Migration: chat safety tables (attachment policy, member timeouts).

Creates org_chat_settings and org_chat_timeouts straight from
schemas.cql. Additive and idempotent, safe to re-run.

    uv run python -m migrate.chat_safety --dry-run
    uv run python -m migrate.chat_safety
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.chat_safety")

TABLES = ("org_chat_settings", "org_chat_timeouts")


def create_tables(session, cfg: common.Config, cql_path) -> list[str]:  # noqa: ANN001
    created: list[str] = []
    for table in TABLES:
        if common.table_exists(session, cfg.keyspace, table):
            continue
        logger.info(
            "%s: creating table%s.", table, " (dry-run)" if cfg.dry_run else ""
        )
        for stmt in common.schema_statements(cql_path, cfg.keyspace, table):
            if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
                continue
            if not cfg.dry_run:
                session.execute(stmt)
        created.append(table)
    return created


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args("Create the chat safety tables.", argv)
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
        created = create_tables(session, cfg, common.cql_file(args))
        logger.info(
            "chat safety tables: %s%s.",
            ", ".join(created) + " created" if created else "already present",
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
