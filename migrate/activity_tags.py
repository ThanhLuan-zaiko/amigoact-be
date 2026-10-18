"""Migration: community tags on activities (folksonomy).

Creates activities_by_tag and tags_by_slug straight from schemas.cql and
adds activities.tag_names - all additive, IF NOT EXISTS, safe to re-run.

    uv run python -m migrate.activity_tags --dry-run
    uv run python -m migrate.activity_tags
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.activity_tags")

TABLES = ("activities_by_tag", "tags_by_slug")


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


def _column_exists(session, keyspace: str, table: str, column: str) -> bool:  # noqa: ANN001, ANN202
    row = session.execute(
        "SELECT column_name FROM system_schema.columns "
        "WHERE keyspace_name = %s AND table_name = %s "
        "AND column_name = %s",
        [keyspace, table, column],
    ).one()
    return row is not None


def add_tag_names(session, cfg: common.Config) -> bool:  # noqa: ANN001, ANN202
    if _column_exists(session, cfg.keyspace, "activities", "tag_names"):
        return False
    logger.info(
        "activities.tag_names: adding column%s.",
        " (dry-run)" if cfg.dry_run else "",
    )
    if not cfg.dry_run:
        session.execute(
            f"ALTER TABLE {cfg.keyspace}.activities "
            "ADD tag_names list<text>"
        )
    return True


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create the community-tag tables and activities.tag_names.", argv
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
        added = add_tag_names(session, cfg)
        logger.info(
            "tables: created=%d skipped=%d; tag_names: %s%s.",
            stats["created"], stats["skipped"],
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
