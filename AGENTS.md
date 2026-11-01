# AGENTS.md

Instructions for AI coding agents working in `amigoact-be`. These rules override default behavior.

## Project structure

- Do not put code in a `src/` folder. Keep Python packages at the repo root, for example `connector/`.
- CI gate 07 fails if a `src/` folder exists.

## Language

- Write everything in English: identifiers, comments, docstrings, SQL comments, configuration, CI files, logs, and commit messages.
- Exception: `.md` files may be written in Vietnamese.
- Do not use non-ASCII characters in `.py`, `.toml`, `.yml`, `.yaml`, or `.sql` files. CI gate 08 enforces this.
- Exception: `schema.sql` is exempt from gate 08 and may keep its existing Vietnamese comments. Do not add new non-English text to other files.

## File size limits

- Every `.py` file must be at most **350 lines** (CI gate 07). When a file approaches the limit, split it into smaller modules.
- When a file approaches the limit, split it into smaller modules instead of adding more code to it.

## Git: never commit, branch, or push without an explicit command

- Do not run `git commit`, `git push`, `git checkout -b`, `git switch -c`, `git branch`, or `git tag`, and do not open a pull request, unless the user asks for that action in the current message.
- Finishing a code change does not give you permission to commit. Stop after the change, summarize what changed, and wait for the next instruction.
- Approval for one commit or push does not carry over to later ones.
- Do not stage files with `git add` unless the user asks.

## No junk files in the repository

Never create or commit these: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.env` files (only `.env.example` is allowed), log files, `.DS_Store`, `Thumbs.db`, `*.tmp`, `*.bak`, scratch scripts, and generated output.

Put scratch work in the session scratchpad directory, not in the repository. CI gate 10 fails if junk files are tracked.

## Database configuration

- `DATABASE_URL` is read only from `.env`, which is gitignored. Settings never read OS environment variables.
- Do not write a connection string, password, or sample connection value into code, tests, `.env.example`, or CI files. `.env.example` keeps `DATABASE_URL=` empty.
- CI writes `.env` from the `CI_POSTGRES_PASSWORD` secret and starts a throwaway PostgreSQL service.
- App code lives in `connector/`. `config.py` loads settings, `database.py` creates the engine, and `app.py` checks the connection at startup.

## Database reset

- Never reset, drop, truncate, or delete database data on your own. Run `scripts/reset_database.py --apply` only when the user explicitly asks for a reset in the current message.
- Without `--apply`, the script is a read-only dry run. It is safe to run to inspect the target.
- The script touches only the database named in `DATABASE_URL` in `.env`. It refuses `postgres`, `template0`, and `template1`, and it asks the user to type the database name before it changes anything.
- A reset drops the `public` schema of that database, which removes every table and its data, then loads `schema.sql` in one transaction.
- Do not write tests that reset the database. Integration tests use the same `.env` database as local development.

## Commands

```bash
uv sync                      # install locked dependencies
uv add <package>             # add a dependency; commit pyproject.toml and uv.lock together
uv run main.py               # run the app entry point
uv run fastapi dev connector/app.py         # run the API; the log shows whether the database connected
uv run ruff check .          # lint
uv run ruff format --check . # format check (run `uv run ruff format .` to fix)
uv run mypy <files>          # type check
uv run pytest                # tests
uv run python scripts/reset_database.py   # dry run only: shows the target and tables, changes nothing
uv lock --check              # verify the lockfile is in sync
```

## Testing rules for API endpoints

- Every new or changed API endpoint must come with three kinds of tests in the same change:
  - **Unit tests** for the logic the endpoint uses (services, validators, helpers). They must not touch the database or the network.
  - **Integration tests** that call the endpoint through the HTTP layer (FastAPI test client). They check the status code, the response body, and the database effects.
  - **Regression tests** that reproduce the bug the change fixed, or lock in existing behavior the endpoint must keep, so later changes cannot break it silently.
- Put tests in `tests/unit/`, `tests/integration/`, and `tests/regression/`, and name them `test_*.py`. CI gate 06 runs them once they exist.
- Unit tests need no database. Integration tests use the database from `.env`. Regression tests guard behavior that was fixed or must not change.
- Do not consider an endpoint done until all three kinds of tests exist and pass locally with `uv run pytest`.

## CI gates

`.github/workflows/ci.yml` runs 13 gates on every push and pull request:

| Gate | Check |
| ---- | ----- |
| 01 | Lockfile in sync (`uv lock --check`) |
| 02 | Install from lockfile (`uv sync --locked`) |
| 03 | Lint (`ruff check`) |
| 04 | Format (`ruff format --check`) |
| 05 | Type check (`mypy`) |
| 06 | Tests (`pytest`, runs once test files exist; CI starts PostgreSQL) |
| 07 | No `src/` folder, and every `.py` file is at most 350 lines |
| 08 | English only: no non-ASCII in code, config, or SQL |
| 09 | Smoke run (`uv run main.py`) |
| 10 | No junk files tracked |
| 11 | Secret scan (gitleaks) |
| 12 | Workflow lint (actionlint) |
| 13 | Every route path in source is referenced by a test under `tests/` |

Gate 13 only checks that a test mentions each endpoint path. It does not check that the unit, integration, and regression tests exist, so you must still write all three kinds (see the testing rules above).

Before you report a change as done, run the gates you can run locally (01 to 06, 09, 10, and 13) and report the actual results. If a gate fails, fix the code. Do not weaken or skip the gate. Never say CI passes without evidence.

After the user asks you to push, check the run with `gh run list` or `gh pr checks` and report the result.
