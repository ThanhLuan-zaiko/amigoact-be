"""Reset the database named in .env by reloading schema.sql.

Without --apply this script only reports what it would do and changes nothing.
With --apply it creates the database if the server does not have it yet, then
drops the public schema and reloads schema.sql.
"""

import argparse
import sys

from sqlalchemy import create_engine, make_url

from src.config import get_settings
from src.reset import (
    SCHEMA_FILE,
    create_database,
    database_exists,
    database_name,
    list_public_tables,
    reset_database,
)


def confirm(name: str, prompt: str) -> bool:
    typed = input(prompt.format(name=name))
    if typed.strip() == name:
        return True
    print("Confirmation did not match. Nothing was changed.")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create the database if missing, delete all data and reload schema.sql",
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

    created = False
    if not database_exists(database_url):
        print(f"Database '{name}' does not exist on the server yet.")
        if not args.apply:
            print(
                "Dry run: nothing was changed. "
                "Run with --apply to create it and load the schema."
            )
            return 0
        if not confirm(
            name,
            "This creates database '{name}' and loads the schema. "
            "Type the database name to confirm: ",
        ):
            return 1
        create_database(database_url)
        print(f"Created database '{name}'.")
        created = True

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        tables = list_public_tables(engine)
        print(f"Tables in public schema now: {len(tables)}")
        for table in tables:
            print(f"  - {table}")

        if not args.apply:
            print("Dry run: nothing was changed. Run with --apply to reset.")
            return 0

        if not created and not confirm(
            name,
            "This deletes ALL data in '{name}'. Type the database name to confirm: ",
        ):
            return 1

        reset_database(engine, schema_sql)
        print(f"Reset complete: '{name}' now matches {SCHEMA_FILE.name}.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
