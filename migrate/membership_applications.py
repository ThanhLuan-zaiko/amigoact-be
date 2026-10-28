"""Migration: create the membership application tables.

Adds membership_forms (per-org application questions, with choice options and
"Khác"), membership_form_settings (the form heading) and
membership_applications (one submission per applicant) from
schemas.cql when they are missing. organization_members and
members_by_user need no DDL: their status column is plain text and
gains the value "applied". Existing rows are not touched. Idempotent:
tables are created only when absent and missing columns of an existing
table (submitted_at, rejected_at) are added, so re-running reports 0.

    uv run python -m migrate.membership_applications --dry-run
    uv run python -m migrate.membership_applications
"""

from __future__ import annotations

import logging
import sys

from migrate import common
from migrate.activity_tags import _column_exists

logger = logging.getLogger("migrate.membership_applications")

TABLES = (
    "membership_forms",
    "membership_applications",
    "membership_form_settings",
)
# Columns that may be missing when a table predates the final schema.
COLUMNS = (
    ("membership_applications", "submitted_at", "timestamp"),
    ("membership_applications", "rejected_at", "timestamp"),
    ("membership_forms", "options", "text"),
    ("membership_forms", "allow_other", "boolean"),
)


def run(session, keyspace: str, cql_path, dry_run: bool) -> dict[str, int]:  # noqa: ANN001
    """Create each missing table from schemas.cql; return counters."""
    created = 0
    for table in TABLES:
        if common.table_exists(session, keyspace, table):
            logger.info("%s already exists; skipping.", table)
            continue
        for stmt in common.schema_statements(cql_path, keyspace, table):
            if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
                continue
            logger.info(
                "%s DDL%s:\n%s",
                table, " (dry-run)" if dry_run else "", stmt,
            )
            if not dry_run:
                session.execute(stmt)
        created += 1
    added = 0
    for table, column, cql_type in COLUMNS:
        if _column_exists(session, keyspace, table, column):
            continue
        logger.info(
            "%s.%s: adding column%s.",
            table, column, " (dry-run)" if dry_run else "",
        )
        if not dry_run:
            session.execute(f"ALTER TABLE {keyspace}.{table} ADD {column} {cql_type}")
        added += 1
    return {"tables_created": created, "columns_added": added}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create membership_forms and membership_applications tables.",
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
        stats = run(session, cfg.keyspace, common.cql_file(args), cfg.dry_run)
        logger.info(
            "membership_applications: tables_created=%d columns_added=%d%s.",
            stats["tables_created"],
            stats["columns_added"],
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
