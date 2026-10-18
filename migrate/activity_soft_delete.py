"""Migration: activity trash lifecycle (soft delete / restore / purge).

Creates activities_trash_by_org straight from schemas.cql and adds
activities.deleted_at - all additive, IF NOT EXISTS, safe to re-run.

    uv run python -m migrate.activity_soft_delete --dry-run
    uv run python -m migrate.activity_soft_delete
"""

from __future__ import annotations

import logging
import sys

from migrate import common
from migrate.activity_tags import _column_exists

logger = logging.getLogger("migrate.activity_soft_delete")


def create_trash_table(session, cfg: common.Config, cql_path) -> int:  # noqa: ANN001, ANN202
    table = "activities_trash_by_org"
    if common.table_exists(session, cfg.keyspace, table):
        return 0
    stmts = common.schema_statements(cql_path, cfg.keyspace, table)
    logger.info("%s: creating table%s.", table, " (dry-run)" if cfg.dry_run else "")
    for stmt in stmts:
        if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
            continue
        if not cfg.dry_run:
            session.execute(stmt)
    return 1


def add_deleted_at(session, cfg: common.Config) -> bool:  # noqa: ANN001, ANN202
    if _column_exists(session, cfg.keyspace, "activities", "deleted_at"):
        return False
    logger.info(
        "activities.deleted_at: adding column%s.",
        " (dry-run)" if cfg.dry_run else "",
    )
    if not cfg.dry_run:
        session.execute(
            f"ALTER TABLE {cfg.keyspace}.activities "
            "ADD deleted_at timestamp"
        )
    return True


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create activities_trash_by_org and activities.deleted_at.", argv
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
        created = create_trash_table(session, cfg, common.cql_file(args))
        added = add_deleted_at(session, cfg)
        logger.info(
            "activities_trash_by_org: %s; deleted_at: %s%s.",
            "created" if created else "already present",
            "added" if added else "already present",
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
