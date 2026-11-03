"""Move stored files into the flat media root, <asset_id>.<ext>, and drop the old hard links.

Run it with the application stopped. Without --apply this script only reports what it
would change and changes nothing.
"""

import argparse

from sqlalchemy.orm import Session

from src.config import get_settings
from src.database import create_database_engine
from src.media.layout_migration import run
from src.media.storage import get_media_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="move the files, update the rows, and remove the old hard links",
    )
    args = parser.parse_args()

    root = get_media_root()
    engine = create_database_engine(get_settings().database_url)
    with Session(engine) as db:
        report = run(db, root, apply=args.apply)

    mode = "applied" if args.apply else "dry run, nothing changed"
    print(f"Media layout migration ({mode}) in {root}")
    print(f"  files to move:              {report.moved}")
    print(f"  hard links to remove:       {report.links_removed}")
    print(f"  already flat:               {report.already_flat}")
    print(f"  files missing on disk:      {report.missing_file}")
    print(f"  target name already taken:  {report.conflicts}")
    print(f"  rows with an unknown key:   {report.skipped}")
    print(f"  files left in account tree: {len(report.leftover_files)}")
    for path in report.leftover_files:
        print(f"    {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
