"""Migration: create chat_attachment_claims and backfill existing sends.

`chat_attachment_claims` records the single message a staged chat file
is attached to (INSERT IF NOT EXISTS at send time), so one file can
never silently serve two messages. Every media id already referenced by
org_room_messages.attachments_json gets a claim row backfilled; staged
files that were never sent keep no claim, so the new staged-discard
endpoint can remove them later.

The pass is idempotent (CREATE TABLE IF NOT EXISTS + INSERT IF NOT
EXISTS); re-running reports zero new claims.

    uv run python -m migrate.chat_attachment_claims --dry-run
    uv run python -m migrate.chat_attachment_claims
"""

from __future__ import annotations

import json
import logging
import sys
from uuid import UUID

from core.security import utcnow
from migrate import common

logger = logging.getLogger("migrate.chat_attachment_claims")

MESSAGES = (
    "SELECT room_id, message_id, attachments_json, created_at"
    " FROM {ks}.org_room_messages"
)
INSERT = (
    "INSERT INTO {ks}.chat_attachment_claims"
    " (media_id, room_id, message_id, created_at)"
    " VALUES (?, ?, ?, ?) IF NOT EXISTS"
)
TABLE = "chat_attachment_claims"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = common.parse_args(__doc__.splitlines()[0])
    cfg = common.resolve_config(args)
    cluster, session = common.connect(cfg)
    try:
        ddl = common.schema_statements(
            common.cql_file(args), cfg.keyspace, TABLE
        )
        created = common.table_exists(session, cfg.keyspace, TABLE)
        if cfg.dry_run:
            for stmt in ddl:
                logger.info("[dry-run] %s", stmt)
        elif not created:
            for stmt in ddl:
                session.execute(stmt)

        planned = applied = 0
        prepared = session.prepare(
            INSERT.format(ks=cfg.keyspace)
        ) if not cfg.dry_run else None
        for row in session.execute(MESSAGES.format(ks=cfg.keyspace)):
            try:
                items = json.loads(row.attachments_json or "[]")
            except json.JSONDecodeError:
                continue
            for item in items:
                try:
                    media_id = UUID(str(item.get("media_id")))
                except (TypeError, ValueError):
                    continue
                planned += 1
                if prepared is not None:
                    outcome = session.execute(
                        prepared,
                        [
                            media_id,
                            row.room_id,
                            row.message_id,
                            row.created_at or utcnow(),
                        ],
                    )
                    if getattr(outcome, "was_applied", False):
                        applied += 1
        logger.info(
            "claims: %d attachment references seen, %d backfilled%s",
            planned,
            applied,
            " (dry-run)" if cfg.dry_run else "",
        )
    finally:
        cluster.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
