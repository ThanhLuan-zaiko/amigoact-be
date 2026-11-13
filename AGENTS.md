# AGENTS.md

Instructions for AI coding agents working in `amigoact-be`. These rules override default behavior.

## Project structure

- Application code lives in the `src/` package. Imports use the package name, for example `from src.config import get_settings`.
- `scripts/`, `tests/`, and `main.py` stay at the repo root.

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
- The project uses its own database `amigoact` on the PostgreSQL server. Never point `DATABASE_URL` at a database shared with other applications, because a reset drops the whole `public` schema of that database.
- Do not write a connection string, password, or sample connection value into code, tests, `.env.example`, or CI files. `.env.example` keeps `DATABASE_URL=` empty.
- CI writes `.env` from the `CI_POSTGRES_PASSWORD` secret with a random `JWT_SECRET`, starts a throwaway PostgreSQL service, and loads `schema.sql` into it.
- App code lives in `src/`. `config.py` loads settings, `database.py` creates the engine, and `app.py` checks the connection at startup.

## Authentication

- Details are in `docs/authentication.md`.
- Code lives in `src/auth/`. Passwords use Argon2id (`passwords.py`). Primary keys are UUIDv7 from `uuid.uuid7()`.
- Access tokens are short-lived HS256 JWTs signed with `JWT_SECRET` from `.env`. Each request also checks that the session is not revoked, so logout takes effect immediately.
- Refresh tokens are opaque and rotate on every use. Only their SHA-256 hash is stored. `auth_sessions.session_id` equals `auth_refresh_tokens.family_id`. Reusing a rotated token after the grace window ends the session.
- API errors use `detail` as a stable code from `src/auth/errors.py`. The frontend translates the codes.
- Without `SMTP_HOST`, emails with their secret links go to the application log. Always set `SMTP_HOST` in production.
- Every HTTP request needs the `X-Internal-Key` header equal to `INTERNAL_API_KEY` from `.env` (`src/internal_key.py`). It is checked before routing and validation, so callers without it get 401 `internal_key_invalid`, never 422. Only the realtime socket (`/ws`, alias `/ws/chat`) is exempt. Test clients send it through `internal_headers()` in `tests/conftest.py`. Details are in `docs/security.md`.
- Allowed browser origins come from `CORS_ORIGINS` in `.env` (`src/cors.py`): exact origins only, no wildcard, empty allows none. The realtime socket refuses a listed-origin mismatch with close code 4403.
- Rate limits use the client IP. Behind a proxy, set uvicorn `--forwarded-allow-ips` to the proxy address so `X-Forwarded-For` is trusted only from there.

## Roles and permissions

- Details are in `docs/roles.md`. Code lives in `src/organizations/` (`permissions.py`, `access.py`, `roles.py`, `role_router.py`).
- Check access with `require_permission(db, org, user_id, ACTIVITIES_CREATE)` or `access.has(...)`; codes are "module.action", so one role can create without deleting. Do not test `role == "admin"`: the coarse role only drives the interface. The owner holds every permission.
- A person changes only roles and people below their own top role, and only hands out permissions they hold. A new permission goes into `permissions.py`, the `permissions` seed in `schema.sql`, and `PermissionCode` in `role_schemas.py`; a unit test keeps them in step.

## Organizations and validation

- Details are in `docs/organizations.md`. Code lives in `src/organizations/`.
- Any logged-in user can create an organization and becomes its owner. Volunteers do not have to be students.
- Shared validators live in `src/validation.py`. Single-line and multi-line text reject control characters, because NUL crashes PostgreSQL. Path IDs use the `Uuid7` type.
- New request bodies reject unknown fields with `extra="forbid"`. Every validation error needs a stable `type` code that the frontend can translate.
- Numbers and flags in request bodies use `StrictInt`, `StrictFloat`, `StrictDecimal`, and `StrictBool` from `src/validation.py`, so `"5"` is not read as 5 and `"true"` is not read as true. Titles people read use `has_letter` (`text_needs_letter`).

## Realtime

- Details are in `docs/realtime.md`. Code lives in `src/realtime/`. Do not open other sockets or keep other hubs.
- Send live events with `bus.emit(db, topic, body)` before the commit, or `bus.publish` after it. Events are small signals; pages refetch through the API.
- When someone loses access, call `bus.revoke` for the topics they lost, because a socket checks access only when it subscribes.
- Every POST, PUT, PATCH, and DELETE route must be listed in `src/realtime/coverage.py` as `emits:`, `none:`, or `pending:`. A unit test fails otherwise.

## Activities

- Details are in `docs/activities.md`. Code lives in `src/activities/`.
- Every seat change locks the activity row first with `load_activity(..., lock=True)`, so the last seat cannot be taken twice. Every registration status change writes a `registration_status_history` row.
- Rules that need the database report errors with `validation_failure` from `src/validation.py`, in the same shape as schema errors.

## Posts

- Details are in `docs/posts.md`. Code lives in `src/posts/`.
- Deleting a draft removes it for good. Deleting a published post sets `deleted_at` and `deleted_by`; it stays in the trash for `TRASH_DAYS` and expired posts are purged when the trash is read. Only the owner purges; owners and admins restore.
- Comments are soft deleted and keep their place with an empty body. Authors edit them within `COMMENT_EDIT_MINUTES`.

## Attendance and hours

- Details are in `docs/attendance.md`. Code lives in `src/attendance/`.
- A scanned QR counts at once. A typed code waits for a manager. Use `is_verified` instead of checking `verified_by` alone.
- `volunteer_hour_ledger` is append-only: a correction is a new `adjustment` row. Hours are summed from the ledger.

## Database reset

- Never reset, drop, truncate, or delete database data on your own. Run `scripts/reset_database.py --apply` only when the user explicitly asks for a reset in the current message.
- Without `--apply`, the script is a read-only dry run. It is safe to run to inspect the target.
- The script touches only the database named in `DATABASE_URL` in `.env`. It refuses `postgres`, `template0`, and `template1`, and it asks the user to type the database name before it changes anything. With `--apply` it creates the database first if the server does not have it (connecting to the `postgres` maintenance database); without `--apply` it never creates anything.
- A reset drops the `public` schema of that database, which removes every table and its data, then loads `schema.sql` in one transaction.
- Do not write tests that reset the database. Integration tests use the same `.env` database as local development.

## Commands

```bash
uv sync                      # install locked dependencies
uv add <package>             # add a dependency; commit pyproject.toml and uv.lock together
uv run main.py               # run the app entry point
uv run uvicorn src.app:app --reload --port 8100   # run the API; the log shows whether the database connected
uv run ruff check .          # lint
uv run ruff format --check . # format check (run `uv run ruff format .` to fix)
uv run mypy <files>          # type check
uv run pytest                # tests
uv run python scripts/reset_database.py   # dry run only: shows the target and tables, changes nothing
uv lock --check              # verify the lockfile is in sync
```

## Documentation

- Write detailed documentation in `docs/`, one file per topic. Keep `README.md` short: setup, commands, and links to `docs/`.
- When behavior changes, update the matching file in `docs/` in the same change.

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
| 07 | Every `.py` file is at most 350 lines |
| 08 | English only: no non-ASCII in code, config, or SQL |
| 09 | Smoke run (`uv run main.py`) |
| 10 | No junk files tracked |
| 11 | Secret scan (gitleaks) |
| 12 | Workflow lint (actionlint) |
| 13 | Every route path in source is referenced by a test under `tests/` |

Gate 13 only checks that a test mentions each endpoint path. It does not check that the unit, integration, and regression tests exist, so you must still write all three kinds (see the testing rules above).

Before you report a change as done, run the gates you can run locally (01 to 06, 09, 10, and 13) and report the actual results. If a gate fails, fix the code. Do not weaken or skip the gate. Never say CI passes without evidence.

After the user asks you to push, check the run with `gh run list` or `gh pr checks` and report the result.
