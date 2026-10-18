"""Migration: drop media_by_owner rows that point at non-gallery assets.

The media_ownership pass re-labelled chat/post rows but left their
org-feed index rows behind. They are already unreachable (list_gallery
filters owner type and role), but stale index rows are dead weight and
future readers must not be able to trip over them: each row whose
asset is missing or no longer organization-owned is deleted.

Only DELETEs on media_by_owner feed rows are issued; media_assets and
file bytes are untouched. Idempotent: re-running reports zero stale.

    uv run python -m migrate.stale_owner_feeds --dry-run
    uv run python -m migrate.stale_owner_feeds
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.stale_owner_feeds")

FEEDS = "SELECT owner_id, created_at, asset_id FROM {ks}.media_by_owner"
ASSET = (
    "SELECT owner_type FROM {ks}.media_assets WHERE asset_id = ?"
)
DELETE = (
    "DELETE FROM {ks}.media_by_owner"
    " WHERE owner_id = ? AND created_at = ? AND asset_id = ?"
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = common.parse_args(__doc__.splitlines()[0])
    cfg = common.resolve_config(args)
    cluster, session = common.connect(cfg)
    try:
        seen = stale = 0
        asset_q = session.prepare(ASSET.format(ks=cfg.keyspace))
        delete_q = session.prepare(DELETE.format(ks=cfg.keyspace))
        for link in session.execute(FEEDS.format(ks=cfg.keyspace)):
            seen += 1
            asset = session.execute(asset_q, [link.asset_id]).one()
            if asset is not None and asset.owner_type == "organization":
                continue
            stale += 1
            logger.info(
                "stale feed row: owner %s -> asset %s (%s)",
                link.owner_id,
                link.asset_id,
                "missing" if asset is None else asset.owner_type,
            )
            if not cfg.dry_run:
                session.execute(
                    delete_q,
                    [link.owner_id, link.created_at, link.asset_id],
                )
        logger.info(
            "feeds: %d rows scanned, %d stale removed%s",
            seen,
            stale,
            " (dry-run)" if cfg.dry_run else "",
        )
    finally:
        cluster.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
