"""Migration: certificates_by_id lookup table for PDF downloads.

Adds the new read model from schemas.cql (certificates_by_id) and
backfills it from the canonical certificates table so certificates
issued before this change still resolve for file downloads.

Everything is additive and idempotent: DDL uses IF NOT EXISTS and the
backfill is a plain upsert-by-key. Re-running is always safe.

    uv run python -m migrate.certificate_files --dry-run
    uv run python -m migrate.certificate_files
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.certificate_files")

TABLE = "certificates_by_id"


def apply_ddl(session, cfg: common.Config, cql_path) -> None:  # noqa: ANN001, ANN202
    if common.table_exists(session, cfg.keyspace, TABLE):
        logger.info("%s: table already present.", TABLE)
        return
    # schema_statements returns the CREATE TABLE already keyspace-qualified.
    stmts = common.schema_statements(cql_path, cfg.keyspace, TABLE)
    logger.info("%s: creating table%s.", TABLE,
                " (dry-run)" if cfg.dry_run else "")
    for stmt in stmts:
        if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
            continue
        if not cfg.dry_run:
            session.execute(stmt)


def backfill(session, cfg: common.Config) -> dict[str, int]:  # noqa: ANN001, ANN202
    """Mirror every canonical certificate row into the by-id feed."""
    stats = {"scanned": 0, "written": 0}
    if not common.table_exists(session, cfg.keyspace, TABLE):
        logger.warning("%s missing; skipping backfill.", TABLE)
        return stats
    scan = session.execute(
        f"SELECT certificate_id, activity_id, student_id "
        f"FROM {cfg.keyspace}.certificates"
    )
    scan.fetch_size = common.FETCH_SIZE
    for row in scan:
        stats["scanned"] += 1
        if row.certificate_id is None:
            continue
        if cfg.dry_run:
            continue
        session.execute(
            f"INSERT INTO {cfg.keyspace}.{TABLE} "
            "(certificate_id, activity_id, student_id) "
            "VALUES (%s,%s,%s)",
            (row.certificate_id, row.activity_id, row.student_id),
        )
        stats["written"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Add certificates_by_id and backfill it from certificates.",
        argv,
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
        apply_ddl(session, cfg, common.cql_file(args))
        stats = backfill(session, cfg)
        logger.info(
            "backfill%s: scanned=%d written=%d.",
            " (dry-run)" if cfg.dry_run else "",
            stats["scanned"],
            stats["written"],
        )
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1
    finally:
        cluster.shutdown()


if __name__ == "__main__":
    sys.exit(main())
