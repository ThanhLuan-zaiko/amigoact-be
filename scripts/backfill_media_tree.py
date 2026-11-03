"""Move files stored before the account tree into it, and add the missing links.

Without --apply this script only reports what it would change and changes nothing.
"""

import argparse

from sqlalchemy.orm import Session

from src.config import get_settings
from src.database import create_database_engine
from src.media.backfill import run
from src.media.storage import get_media_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="move the files and write the links",
    )
    args = parser.parse_args()

    root = get_media_root()
    engine = create_database_engine(get_settings().database_url)
    with Session(engine) as db:
        report = run(db, root, apply=args.apply)

    mode = "applied" if args.apply else "dry run, nothing changed"
    print(f"Backfill ({mode}) in {root}")
    print(f"  files to move:        {report.moved}")
    print(f"  links to create:      {report.linked}")
    print(f"  files missing on disk: {report.missing_file}")
    print(f"  rows skipped:         {report.skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
