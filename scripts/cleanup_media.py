"""Remove uploaded files that nothing uses any more.

Without --apply this script only reports what it would remove and changes nothing.
"""

import argparse
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.config import get_settings
from src.database import create_database_engine
from src.media.cleanup import run
from src.media.storage import get_media_root

DEFAULT_MIN_AGE_DAYS = 30


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="mark the unused rows as deleted and remove their files",
    )
    parser.add_argument(
        "--min-age-days",
        type=int,
        default=DEFAULT_MIN_AGE_DAYS,
        help="keep uploads younger than this many days (default: %(default)s)",
    )
    parser.add_argument(
        "--user",
        type=uuid.UUID,
        default=None,
        help="only clean the files uploaded by this user id (files with no row are always included)",
    )
    args = parser.parse_args()
    if args.min_age_days < 0:
        parser.error("--min-age-days must be 0 or more")

    root = get_media_root()
    engine = create_database_engine(get_settings().database_url)
    with Session(engine) as db:
        plan = run(
            db,
            root,
            now=datetime.now(UTC),
            min_age_days=args.min_age_days,
            uploader_id=args.user,
            apply=args.apply,
        )

    mode = "applied" if args.apply else "dry run, nothing changed"
    print(f"Media cleanup ({mode}) in {root}")
    print(f"  uploads to mark deleted: {len(plan.assets)}")
    print(f"  files to remove:         {len(plan.files)}")
    for error in plan.errors:
        print(f"  could not remove {error}")
    return 1 if plan.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
