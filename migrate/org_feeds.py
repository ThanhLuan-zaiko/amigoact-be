"""Migration: org-scoped feed tables + additive api_keys.created_at.

Adds the two new read models from schemas.cql (departments_by_org,
api_keys_by_org), the nullable api_keys.created_at column, and the two
org-listing secondary indexes (hour_rules_by_org,
certificate_templates_by_org). Then backfills both feed tables from
their canonical sources so keys/departments created before the feeds
existed still list correctly.

Everything is additive and idempotent: DDL uses IF NOT EXISTS, the
ALTER runs only when the column is missing, and the backfill is a
plain upsert-by-key. Re-running is always safe.

    uv run python -m migrate.org_feeds --dry-run
    uv run python -m migrate.org_feeds
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.org_feeds")

NEW_TABLES = ("departments_by_org", "api_keys_by_org")
NEW_INDEXES = (
    ("hour_rules", "hour_rules_by_org",
     "CREATE INDEX IF NOT EXISTS hour_rules_by_org "
     "ON {ks}.hour_rules (org_id)"),
    ("certificate_templates", "certificate_templates_by_org",
     "CREATE INDEX IF NOT EXISTS certificate_templates_by_org "
     "ON {ks}.certificate_templates (org_id)"),
)


def _column_exists(session, keyspace: str, table: str, column: str) -> bool:
    row = session.execute(
        "SELECT column_name FROM system_schema.columns "
        "WHERE keyspace_name = %s AND table_name = %s AND column_name = %s",
        [keyspace, table, column],
    ).one()
    return row is not None


def _index_exists(session, keyspace: str, table: str, index: str) -> bool:
    row = session.execute(
        "SELECT index_name FROM system_schema.indexes "
        "WHERE keyspace_name = %s AND table_name = %s AND index_name = %s",
        [keyspace, table, index],
    ).one()
    return row is not None


def apply_ddl(session, cfg: common.Config, cql_path) -> None:
    for table in NEW_TABLES:
        if common.table_exists(session, cfg.keyspace, table):
            logger.info("%s: table already present.", table)
            continue
        stmts = common.schema_statements(cql_path, cfg.keyspace, table)
        logger.info("%s: creating table%s.", table,
                    " (dry-run)" if cfg.dry_run else "")
        for stmt in stmts:
            if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
                continue
            if not cfg.dry_run:
                session.execute(stmt)
    if _column_exists(session, cfg.keyspace, "api_keys", "created_at"):
        logger.info("api_keys.created_at: column already present.")
    else:
        logger.info("api_keys.created_at: adding column%s.",
                    " (dry-run)" if cfg.dry_run else "")
        if not cfg.dry_run:
            session.execute(
                f"ALTER TABLE {cfg.keyspace}.api_keys "
                "ADD created_at timestamp"
            )
    for table, index, stmt_tpl in NEW_INDEXES:
        if _index_exists(session, cfg.keyspace, table, index):
            logger.info("%s: index already present.", index)
            continue
        logger.info("%s: creating index%s.", index,
                    " (dry-run)" if cfg.dry_run else "")
        if not cfg.dry_run:
            session.execute(stmt_tpl.format(ks=cfg.keyspace))


def backfill_api_keys(session, cfg: common.Config) -> dict[str, int]:
    """Mirror every api_keys row into the org feed (upsert by key)."""
    stats = {"scanned": 0, "written": 0}
    if not common.table_exists(session, cfg.keyspace, "api_keys_by_org"):
        logger.warning("api_keys_by_org missing; skipping backfill.")
        return stats
    scan = session.execute(
        f"SELECT key_id, org_id, key_hash, name, scopes, expires_at, "
        f"revoked_at, last_used_at, created_at "
        f"FROM {cfg.keyspace}.api_keys"
    )
    scan.fetch_size = common.FETCH_SIZE
    for row in scan:
        stats["scanned"] += 1
        if cfg.dry_run:
            continue
        session.execute(
            f"INSERT INTO {cfg.keyspace}.api_keys_by_org (org_id, key_id, "
            "key_hash, name, scopes, expires_at, revoked_at, "
            "last_used_at, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (row.org_id, row.key_id, row.key_hash, row.name, row.scopes,
             row.expires_at, row.revoked_at, row.last_used_at,
             row.created_at),
        )
        stats["written"] += 1
    return stats


def backfill_departments(session, cfg: common.Config) -> dict[str, int]:
    """Mirror canonical departments rows into the org feed."""
    stats = {"scanned": 0, "written": 0}
    if not common.table_exists(session, cfg.keyspace, "departments_by_org"):
        logger.warning("departments_by_org missing; skipping backfill.")
        return stats
    scan = session.execute(
        f"SELECT id, org_id, name, code, campus_id "
        f"FROM {cfg.keyspace}.departments"
    )
    scan.fetch_size = common.FETCH_SIZE
    for row in scan:
        stats["scanned"] += 1
        if cfg.dry_run:
            continue
        session.execute(
            f"INSERT INTO {cfg.keyspace}.departments_by_org "
            "(org_id, department_id, name, code, campus_id) "
            "VALUES (%s,%s,%s,%s,%s)",
            (row.org_id, row.id, row.name, row.code,
             row.campus_id),
        )
        stats["written"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Add org feed tables, api_keys.created_at, org-listing indexes.",
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
        for name, fn in (
            ("api_keys_by_org", backfill_api_keys),
            ("departments_by_org", backfill_departments),
        ):
            stats = fn(session, cfg)
            logger.info(
                "%s backfill%s: scanned=%d written=%d.",
                name,
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
