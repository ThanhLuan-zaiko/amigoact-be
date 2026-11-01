"""Reset the database named in .env by reloading schema.sql.

Without --apply this script only reports what it would do and changes nothing.
"""

import argparse
import sys

from sqlalchemy import create_engine, make_url

from src.config import get_settings
from src.reset import (
    SCHEMA_FILE,
    database_name,
    list_public_tables,
    reset_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete all data and reload schema.sql",
    )
    args = parser.parse_args()

    database_url = get_settings().database_url
    try:
        name = database_name(database_url)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    url = make_url(database_url)
    print(f"Target: {url.host}:{url.port}/{name} as user '{url.username}'")
    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        tables = list_public_tables(engine)
        print(f"Tables in public schema now: {len(tables)}")
        for table in tables:
            print(f"  - {table}")

        if not args.apply:
            print("Dry run: nothing was changed. Run with --apply to reset.")
            return 0

        typed = input(
            f"This deletes ALL data in '{name}'. Type the database name to confirm: "
        )
        if typed.strip() != name:
            print("Confirmation did not match. Nothing was changed.")
            return 1

        reset_database(engine, schema_sql)
        print(f"Reset complete: '{name}' now matches {SCHEMA_FILE.name}.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
