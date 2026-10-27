# AGENTS.md — amigoact-be

Source of truth for AI agents and contributors. Follow it strictly; add a rule here before using a new pattern.

## Stack and run
- Python >= 3.14 with `uv`; `fastapi` only (no uvicorn, gunicorn or hypercorn). ScyllaDB via `cassandra.cqlengine`, Argon2id (`argon2-cffi`) for passwords, `pyjwt`, `pydantic-settings`.
- `main.py` exposes `app: FastAPI`. Run with `fastapi dev main.py --port 8100`. `GET /health` must always work.

## Structure
- No `src/`. Each feature is a root folder: `model.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`, `interfaces.py`. Shared code lives only in `core/`.
- Routers do HTTP only. Services hold rules and never import FastAPI. Only `model.py` and `repository.py` touch cqlengine.
- Cross-feature imports go through `interfaces.py` and `core/dependencies.py`. Every `.py` file <= 350 lines.

## Data and security
- Primary keys: UUIDv7 (`uuid_utils.uuid7()`) stored as `uuid`. Never `uuid4` or integer PKs.
- No string-built CQL, no `ALLOW FILTERING`. Use LWT only where correctness needs it.
- Raw CQL goes through `core/cql.py`: `run()` (prepared, cached per query) and `claim()` for `IF NOT EXISTS` with an ownership re-read after timeouts. Never call `session.execute` directly in features.
- Cluster settings come only from `core/database.cluster_options()`. Process-local caches use `core.cql.TtlCache` (short TTL, cleared on every write).
- Schema changes go through `migrate/` modules: idempotent, non-destructive, `--dry-run` first.
- Access token: JWT, 5–15 min, `Authorization: Bearer`. Refresh token: opaque 256-bit value in an `HttpOnly` cookie, stored as a SHA-256 hash, rotated on every use, family revoked on reuse.
- Authentication is not authorization: check ownership or role in the service layer on every access.
- WebSocket: one-time ticket from `POST /ws/tickets`, then `GET /ws?ticket=`. Authorize every channel subscription.

## API
- JSON only; lowercase UUIDs; UTC ISO-8601 datetimes. Errors use `{"code": "EMAIL_TAKEN", "message": "..."}` with English codes and messages.
- `201` + `Location` on create, `204` on delete and logout, `400`/`401`/`403`/`404`/`409` as appropriate.
- Frontend and backend ship together: every new or changed error `code` is handled in the frontend copy table in the same change.

## Quality and git
- Every feature ships unit, integration and regression tests; `uv run pytest -q` must pass.
- Python code, comments and logs in English; never log secrets. Other `.md` files are Vietnamese.
- Never commit, push, reset the database or build Docker images unless the user explicitly asks.
- Never commit junk (`__pycache__/`, `.venv/`, `.env`, `.pytest_cache/`); never `git add -A`. After each task, run `git status --short` and report it.
