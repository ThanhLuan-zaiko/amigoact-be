"""Migration: delete chat media assets that nothing references.

A chat file is live while a room-media index row points at it (attached
to a message) or a claim row exists (single-use send in flight or still
awaiting its one send). Rows with neither and older than the grace
window are leftovers: staged uploads whose uploader closed the tab
before the discard endpoint ran, or pre-claim-era rows orphaned when
their message was deleted.

For every orphan the asset row, its hash/uploader index rows, any stale
org-feed row, and the bytes under MEDIA_ROOT are removed. Idempotent:
re-running reports zero orphans. Staged files younger than
``--min-age-hours`` (default 24) are kept so an upload still being
composed is never swept.

    uv run python -m migrate.orphan_chat_media --dry-run
    uv run python -m migrate.orphan_chat_media
    uv run python -m migrate.orphan_chat_media --min-age-hours 1
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from migrate import common
from reset_db import load_dotenv, resolve_path

logger = logging.getLogger("migrate.orphan_chat_media")

REFS = "SELECT media_id FROM {ks}.org_room_media"
CLAIMS = "SELECT media_id FROM {ks}.chat_attachment_claims"
ASSETS = (
    "SELECT asset_id, owner_id, owner_type, file_hash, uploader_id,"
    " storage_key, file_url, created_at FROM {ks}.media_assets"
)
FEED = "SELECT created_at, asset_id FROM {ks}.media_by_owner WHERE owner_id = ?"
FEED_DEL = (
    "DELETE FROM {ks}.media_by_owner"
    " WHERE owner_id = ? AND created_at = ? AND asset_id = ?"
)
HASH = "SELECT asset_id FROM {ks}.media_by_hash WHERE file_hash = ?"
HASH_DEL = "DELETE FROM {ks}.media_by_hash WHERE file_hash = ?"
UPLOADER_DEL = (
    "DELETE FROM {ks}.media_by_uploader"
    " WHERE uploader_id = ? AND created_at = ? AND asset_id = ?"
)
ASSET_DEL = "DELETE FROM {ks}.media_assets WHERE asset_id = ?"


EXTRA_FLAGS = ("--media-root", "--min-age-hours")


def split_args(argv: list[str] | None):
    """Separate this module's extra flags from common's standard ones.

    common.parse_args rejects unknown options, so --media-root and
    --min-age-hours (with their values) are pulled out first and parsed
    here instead.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    extras: list[str] = []
    kept: list[str] = []
    skip_next = False
    for token in raw:
        if skip_next:
            extras.append(token)
            skip_next = False
        elif token in EXTRA_FLAGS:
            extras.append(token)
            skip_next = True
        elif token.startswith(EXTRA_FLAGS) and "=" in token:
            extras.append(token)
        else:
            kept.append(token)
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-root", default="", help="MEDIA_ROOT path.")
    parser.add_argument(
        "--min-age-hours",
        type=float,
        default=24.0,
        help="Keep unreferenced chat assets younger than this.",
    )
    return parser.parse_args(extras), kept


def media_root(args, opts) -> Path:
    env_cfg = load_dotenv(resolve_path(args.env))
    raw = opts.media_root or env_cfg.get("MEDIA_ROOT", "./media")
    return Path(raw).expanduser().resolve()


def remove_bytes(root: Path, storage_key: str | None) -> bool:
    """Unlink one file under the media root; refuses escapes like core."""
    if not storage_key:
        return False
    candidate = (root / storage_key).resolve()
    if candidate == root or root not in candidate.parents:
        logger.warning("skip bytes outside media root: %s", storage_key)
        return False
    if candidate.is_file():
        candidate.unlink()
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    opts, kept = split_args(argv)
    args = common.parse_args(__doc__.splitlines()[0], kept)
    cfg = common.resolve_config(args)
    root = media_root(args, opts)
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=opts.min_age_hours
    )
    cluster, session = common.connect(cfg)
    try:
        ks = cfg.keyspace
        referenced = {
            row.media_id
            for row in session.execute(REFS.format(ks=ks))
            if row.media_id is not None
        }
        claimed = {
            row.media_id
            for row in session.execute(CLAIMS.format(ks=ks))
        }
        feed_q = session.prepare(FEED.format(ks=ks))
        feed_del = session.prepare(FEED_DEL.format(ks=ks))
        hash_q = session.prepare(HASH.format(ks=ks))
        hash_del = session.prepare(HASH_DEL.format(ks=ks))
        up_del = session.prepare(UPLOADER_DEL.format(ks=ks))
        asset_del = session.prepare(ASSET_DEL.format(ks=ks))

        scanned = orphans = bytes_removed = 0
        for asset in session.execute(ASSETS.format(ks=ks)):
            if asset.owner_type != "chat":
                continue
            scanned += 1
            if asset.asset_id in referenced or asset.asset_id in claimed:
                continue
            created = asset.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created is None or created > cutoff:
                continue
            orphans += 1
            logger.info(
                "orphan chat asset: %s (room %s, %s)",
                asset.asset_id,
                asset.owner_id,
                asset.storage_key,
            )
            if cfg.dry_run:
                continue
            for link in session.execute(feed_q, [asset.owner_id]):
                if link.asset_id == asset.asset_id:
                    session.execute(
                        feed_del,
                        [asset.owner_id, link.created_at, asset.asset_id],
                    )
            if asset.file_hash:
                pointed = session.execute(hash_q, [asset.file_hash]).one()
                if pointed is not None and pointed.asset_id == asset.asset_id:
                    session.execute(hash_del, [asset.file_hash])
            if asset.uploader_id is not None and asset.created_at is not None:
                session.execute(
                    up_del,
                    [asset.uploader_id, asset.created_at, asset.asset_id],
                )
            session.execute(asset_del, [asset.asset_id])
            if remove_bytes(root, asset.storage_key or asset.file_url):
                bytes_removed += 1
        logger.info(
            "chat assets: %d scanned, %d orphans removed, %d files deleted%s",
            scanned,
            orphans,
            bytes_removed,
            " (dry-run)" if cfg.dry_run else "",
        )
    finally:
        cluster.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
