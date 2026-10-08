# AGENTS.md — amigoact-be

This file is the source of truth for AI agents and human contributors working in `amigoact-be`.
Follow it strictly. Do not introduce patterns outside this document without updating it first.

## 1. Stack (Locked)

- Language: Python `>=3.14` (see `pyproject.toml`).
- Package manager: `uv`.
- Web framework: `fastapi>=0.142.4` only.
- Database: ScyllaDB.
- DB driver + ORM: `cassandra-driver`, used through `cassandra.cqlengine` (ORM-style).
- Password hashing: Argon2id via `argon2-cffi` only.
- Primary keys: UUIDv7 only, stored as CQL `uuid`.
- UUID generator: `uuid-utils` (`uuid_utils.uuid7()`).
- JWT: `pyjwt` + `cryptography`.
- Validation/settings: Pydantic v2 (`pydantic`, `pydantic-settings`).
- Tests: `pytest`, `pytest-asyncio`, `httpx`.

Do not add alternatives (SQLAlchemy, Alembic, bcrypt, passlib-bcrypt, `uuid4` PKs, Django ORM, Tortoise ORM).

## 2. Runtime Rule: FastAPI Only, Port 8100

1. Install `fastapi` only. Do NOT add `uvicorn`, `gunicorn`, `hypercorn`, `daphne`, or any WSGI/ASGI server.
2. Forbidden in code and dependencies:
   - `import uvicorn`
   - `uvicorn.run(...)`
   - `app.run(...)`
3. The application entrypoint MUST expose a module-level variable:
   ```python
   app: FastAPI = FastAPI(...)
   ```
4. Run only with the FastAPI CLI on port `8100`:
   ```bash
   # development
   fastapi dev main.py --port 8100

   # production
   fastapi run main.py --port 8100
   ```
   `main.py` lives at the repository root (`amigoact-be/main.py`). Keep the same CLI shape and `--port 8100`.
5. No hard-coded host/port inside source code. Host/port belong to the run command, environment, or deployment config.
6. Health check endpoint is mandatory: `GET /health` returns `{"status": "ok"}` without auth or DB dependency failure masking.

## 3. Project Structure: No `src/`, One Folder per Feature at Root

`src/` is forbidden. Do not create `src/`, `src/modules/`, or `src/<feature>/` under any circumstance.
Every feature is a top-level folder directly under `amigoact-be/`. Shared code lives only in top-level `core/`. The FastAPI entrypoint is top-level `main.py`.

```text
amigoact-be/
  main.py              # app factory, middleware, router registration, lifespan only
  core/
    config.py          # pydantic-settings only
    database.py        # single cqlengine connection + sync_table place
    security.py        # JWT + opaque-token helpers, no business logic
    hashing.py         # Argon2id wrapper only
    dependencies.py    # FastAPI Depends wiring (interfaces -> implementations)
    exceptions.py      # domain exceptions + handlers
  auth/                # feature example
    model.py           # cqlengine Model(s) for this feature only
    schemas.py         # Pydantic request/response DTOs
    repository.py      # persistence only, cqlengine calls only
    service.py         # business rules only, no FastAPI / no CQL strings
    router.py          # HTTP only: parsing, status codes, Depends, no business logic
    interfaces.py      # ABCs for repository/service (DIP)
  users/               # next feature, same 6-file shape
    model.py
    schemas.py
    repository.py
    service.py
    router.py
    interfaces.py
  <feature>/           # every new feature repeats this shape at root
    model.py
    schemas.py
    repository.py
    service.py
    router.py
    interfaces.py
  tests/
    unit/
    integration/
    regression/
```

Rules:

- Never nest feature code inside `core/`, `tests/`, another feature, or a `src/` folder. If you catch yourself creating `src/`, stop and move the folder to root.
- One root folder = one bounded context (`auth/`, `users/`, `posts/`, ...). No generic `common/`, `utils/` dumping grounds at root; shared code goes to `core/` with justification.
- A feature folder may only be split into more files (e.g. `user_repository.py`, `session_repository.py`, `auth_router.py`) when approaching the 350-line limit, never into sub-feature folders unless the feature is explicitly decomposed and renamed.
- `router.py` must not import `cassandra.cqlengine` directly.
- `model.py` must not contain business rules or password/JWT logic.
- `service.py` must not contain FastAPI (`APIRouter`, `Request`, `Response`, `HTTPException`) except domain exceptions mapped in `core/exceptions.py`.
- Cross-feature imports go through `interfaces.py` + `core/dependencies.py`, never concrete classes directly. Relative imports must not escape the feature folder except to import from `core/`.

## 4. Python File Size Rule: 350 Lines Max

1. Every `*.py` file MUST be `<= 350` lines, including blank lines, comments, docstrings, and tests embedded in source (tests should normally live under `tests/`).
2. Check before commit (root folders only, `src/` must not exist, skip `.venv/`):
   ```bash
   python -c "import pathlib; roots=['.']; bad=[(p, sum(1 for _ in open(p, encoding='utf-8'))) for r in roots for p in pathlib.Path(r).rglob('*.py') if '.venv' not in p.parts and 'src' not in p.parts]; print('\n'.join(f'{p}: {n}' for p, n in bad if n > 350) or 'OK')"
   ```
3. If a file exceeds 350 lines, split it by responsibility, in this order:
   - Extract DTOs -> `schemas_*.py` or split `schemas.py` by resource.
   - Extract interfaces -> `interfaces.py`.
   - Extract helpers/validators -> `utils.py` / `validators.py`.
   - Split repository/service by aggregate (e.g. `user_repository.py`, `session_repository.py`).
   - Split router by resource (e.g. `auth_router.py`, `user_router.py`).
4. Do not split arbitrarily by line number. Each new file must have one clear Single Responsibility and a matching test file.
5. Refactoring that only moves code must preserve public behavior and be covered by existing regression tests.

## 5. Database: ScyllaDB via `cassandra-driver` + `cqlengine`

1. Install and connect with:
   ```bash
   uv add cassandra-driver
   ```
2. Use ORM-style access:
   ```python
   from cassandra.cqlengine import columns, connection, management, models
   ```
3. Connection management lives in exactly one module (e.g. `core/database.py`):
   - `connection.setup(hosts, default_keyspace, protocol_version, ...)`
   - `management.sync_table(...)` only at startup/migration, never per-request.
   - Keyspace, hosts, replication, and credentials come from `pydantic-settings`, never hard-coded.
4. Prefer Models over raw CQL:
   - Define one `Model` per table, table name explicit: `__table_name__ = "users"`.
   - No raw `session.execute("SELECT ...")` except for migrations, complex aggregations, or proven `cqlengine` limitations. Justify with a comment + test.
5. Repository pattern is mandatory:
   - All `Model.objects(...)`, `.save()`, `.update()`, `.delete()` calls live in `repository.py`.
   - Services receive repository interfaces via constructor/Depends injection.
6. Query rules:
   - Design tables around queries. Avoid `ALLOW FILTERING`.
   - Use `LOCAL_QUORUM` for normal reads/writes unless a reason is documented.
   - Use `IF NOT EXISTS` / lightweight transactions (LWT) only where correctness requires it (e.g. unique email index).
   - Never build CQL by string concatenation with user input.
7. Migrations/schema changes must be explicit, reviewable, and covered by an integration test against a test keyspace (e.g. `amigoact_test`).

Example model shape:

```python
import uuid_utils
from cassandra.cqlengine import columns, models

class User(models.Model):
    __table_name__ = "users"
    __keyspace__ = "amigoact"

    id = columns.UUID(primary_key=True, default=uuid_utils.uuid7)
    email = columns.Text(required=True, index=True)
    password_hash = columns.Text(required=True)
    created_at = columns.DateTime(primary_key=False)
```

## 6. Primary Keys: UUIDv7 Only

1. Every new table primary key MUST be CQL `uuid` populated with UUIDv7.
2. Generate in application code:
   ```python
   import uuid_utils
   user_id = uuid_utils.uuid7()
   ```
   Or as cqlengine default: `default=uuid_utils.uuid7`.
3. Forbidden:
   - `uuid.uuid4()` for primary keys.
   - Integer autoincrement, sequences, timestamps alone as PK.
   - Client-supplied PKs unless the API explicitly allows idempotency and validates UUIDv7 format.
4. Serialize UUIDs as lowercase canonical strings in JSON APIs.
5. Time-ordering from UUIDv7 must not be treated as a security boundary; always enforce explicit authorization checks.

## 7. Password Hashing: Argon2id Only

1. Use `argon2-cffi` with Argon2id (`PasswordHasher` defaults to ID). No `bcrypt`, `scrypt`, `pbkdf2`, `sha*`, `md5`.
   ```bash
   uv add argon2-cffi
   ```
2. Centralize in one hasher module (e.g. `core/hashing.py`) with explicit parameters:
   ```python
   from argon2 import PasswordHasher
   ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
   ```
3. Rules:
   - Store only `ph.hash(password)` in `password_hash`. Never store or log plaintext passwords.
   - Verify with `ph.verify(stored_hash, candidate)`; handle `VerifyMismatchError` as invalid credentials with a generic message.
   - If `ph.check_needs_rehash(stored_hash)` is true on successful login, rehash and persist via repository.
   - Enforce credential policy in Pydantic schemas (not in the hasher):
     - Password: minimum 8 characters with at least one uppercase letter, one lowercase letter, one digit, and one special character.
     - Phone (Vietnam): required, matches `^0(3|5|7|8|9)\d{8}$`, and rejects obviously fake numbers (all identical digits, strictly sequential ascending/descending runs).
     - Email and phone must both be unique (`EMAIL_TAKEN`, `PHONE_TAKEN` with `409`).
   - All hashing utils require unit tests: correct verify, wrong-password rejection, rehash path, timing-safe behavior.

## 8. Authentication: Hybrid

“Hybrid” means: **stateless short-lived JWT access token + stateful opaque refresh token**.

1. Access token:
   - Type: JWT (`HS256` or `RS256`), lifetime 5–15 minutes.
   - Transport: `Authorization: Bearer <jwt>`.
   - Claims: `sub` (user UUIDv7 string), `iat`, `exp`, `jti`, `type="access"`, minimal `scopes/roles`.
   - Validated on every protected request by a FastAPI dependency (e.g. `get_current_user`). Reject wrong `type`, expired, or bad signature with `401`, no details leakage.
2. Refresh token:
   - Type: opaque 256-bit random value (`secrets.token_bytes(32)` / `token_urlsafe(32)`).
   - Transport: `HttpOnly; Secure; SameSite=Lax` cookie (and `Path=/auth/refresh` where possible). Never in URL or `localStorage` by design.
   - Storage: SHA-256 hash only in ScyllaDB (e.g. `auth_refresh_tokens` table with `token_hash`, `user_id`, `expires_at`, `revoked_at`, `rotated_from_jti`). Compare hashes with `hmac.compare_digest`.
   - Lifetime: e.g. 7–30 days, absolute expiry + rotation on every use. Detect reuse and revoke the whole token family on suspected theft.
3. Contract ownership (no endpoint catalog here):
   - This file does NOT enumerate endpoints. The contract lives in code (`<feature>/router.py` + `<feature>/schemas.py`) and is surfaced as OpenAPI at `/docs`. A duplicated list here would rot; only the behavior rules below are locked.
   - Contract parity, both directions: every frontend feature MUST have backend support, and every backend capability the product relies on MUST be surfaced in the frontend. Shipping one side without the other fails the Definition of Done. New or changed error `code` values MUST be handled in the frontend copy table in the same change.
   - Locked auth behaviors: registration creates the account without issuing a code yet (verification-mail gate deferred); login currently accepts unverified emails (`EMAIL_NOT_VERIFIED` + `403` returns with the gate); change-password rejects a reused password (`SAME_AS_CURRENT`, `400`).
   - Dev-only `POST /auth/dev/challenge-code` is allowed solely when `ENV=dev`: it issues a fresh verification/reset code for local development without SMTP and returns the plaintext code. It MUST 404 in any other environment and MUST never be called from production builds.
4. Authorization:
   - Authentication != authorization. Every resource access checks ownership/role explicitly in service layer.
   - Roles/scopes come from server-side user record, not blindly trusted claims, except short-lived cached roles with tests.
5. Security hygiene:
   - Secrets via env/settings, never in repo. Separate JWT secret/key from cookie signing.
   - Rate-limit login/refresh, generic error messages (`"Invalid credentials"`), audit login/refresh/reuse events.
   - Full auth flow must have unit + integration + regression tests (login, refresh rotation, reuse detection, logout, expiry).

## 9. SOLID + Effective OOP

Strictly enforced. Reviewers reject violations.

- **S — Single Responsibility:** one class/module has one reason to change. Routers do HTTP, services do rules, repositories do persistence, schemas do validation.
- **O — Open/Closed:** extend via new classes/strategies/handlers, not by editing stable core with `if/else` chains. Use polymorphism for auth providers, token stores, password policies in tests.
- **L — Liskov Substitution:** subclasses/mocks must be drop-in replacements. No strengthened preconditions or narrowed behavior.
- **I — Interface Segregation:** small ABCs in `interfaces.py` (e.g. `UserRepository`, `PasswordHasherPort`, `TokenStore`). No fat interfaces forcing unused methods.
- **D — Dependency Inversion:** high-level services depend on ABCs. Concrete wiring happens only in `core/dependencies.py` via `Depends`.

OOP practices:

- Type hints everywhere (`from __future__ import annotations` where useful). `mypy`/Pylance-clean public APIs.
- Encapsulation: private state, explicit methods, no public mutable class attributes for request state.
- Composition over inheritance. Max one level of inheritance unless justified and tested.
- No god classes, no anemic dumping of logic into routers, no static global DB/session state accessed directly from services.
- Value objects/DTOs with Pydantic v2 (`BaseModel`, `Field`, `field_validator`). Domain exceptions in `core/exceptions.py`, mapped to HTTP in one place.

## 10. Testing: Mandatory Unit + Integration + Regression

Every feature/fix MUST ship with all three levels. No tests = no merge.

- Layout:
  ```text
  tests/unit/test_<thing>.py
  tests/integration/test_<feature>_db.py
  tests/regression/test_<feature>_regression.py
  ```
- `unit`: pure and fast, external I/O mocked. Covers services, validators, Argon2id wrapper (with test-only lowered params), UUIDv7 generation, JWT claims, mappers, edge cases.
- `integration`: FastAPI app (`httpx.ASGITransport`) + real ScyllaDB test keyspace or documented test double with same CQL semantics. Covers router->service->repository->DB, login/refresh rotation, persistence, startup `sync_table`.
- `regression`: locks fixed bugs and contracts. Name the issue/case, freeze request/response shapes, auth flows, and backward compatibility. Must fail before the fix and pass after.
- Commands:
  ```bash
  uv run pytest tests/unit -q
  uv run pytest tests/integration -q
  uv run pytest tests/regression -q
  uv run pytest -q
  ```
- Rules:
  - Use fixtures/factories, isolated test keyspace, cleanup per test. No tests depending on execution order.
  - Never commit real secrets, real password hashes, or production hosts. Use test settings.
  - Async code tested with `pytest-asyncio` (`asyncio_mode = "auto"` recommended).
  - If ScyllaDB is unavailable in CI, integration tests must be clearly skipped with reason, not silently passed.

## 11. API, Errors, and Config Conventions

- JSON only, lowercase UUID strings, UTC ISO-8601 datetimes.
- Use proper status codes: `201` on create with `Location`, `204` with empty body on delete/logout, `400` validation, `401` unauthenticated, `403` unauthorized, `404` not found, `409` conflict (e.g. duplicate email), `422` for Pydantic validation via FastAPI default.
- Single error envelope:
  ```json
  {"code": "EMAIL_TAKEN", "message": "Email is already registered."}
  ```
  Domain exceptions carry `code`; one handler maps them to HTTP.
- Pagination: cursor-based where possible (`limit` + `paging_state`/`next_cursor`); otherwise `limit/offset` with `total` only if cheap.
- Config only via `pydantic-settings` (`core/config.py`) loaded from env. No `os.getenv` scattered in features. Document every new env var in `README.md`.
- Logging: stdlib `logging` with correlation/request IDs; no `print`, no sensitive fields (passwords, tokens, hashes, JWT secrets).

## 12. Dependencies and Forbidden Patterns

Allowed to add (via `uv add`) when needed and documented: `uuid-utils`, `cassandra-driver`, `argon2-cffi`, `pyjwt`, `cryptography`, `pydantic-settings`, `pytest`, `pytest-asyncio`, `httpx`, `testcontainers` (for integration tests).

Forbidden:

- Any ASGI server package (`uvicorn`, `gunicorn`, `hypercorn`).
- Creating a `src/` directory or placing feature code under `src/`, `src/modules/`, `src/<feature>/`. Feature folders must be top-level (`auth/`, `users/`, ...).
- Raw string-concatenated CQL with user input, `ALLOW FILTERING` in new queries without justification.
- `uuid4` PKs, integer PKs, bcrypt/scrypt/MD5/SHA-as-password-hash, plaintext passwords, storing JWT refresh tokens as plaintext.
- Business logic in routers, DB access in routers/services bypassing repositories, global mutable singletons holding request state.
- Authoritative in-memory state (session stores, token caches, rate-limit buckets, dedup sets, locks, QR/slot counters in app RAM). ScyllaDB is the source of truth; use `idempotency_keys`, `auth_rate_limits`, `job_leases`, and LWT conditions instead.
- Files `> 350` lines, untyped public functions, untested features.

## 13. Definition of Done

A task is done only when:

1. `fastapi dev/run --port 8100` starts with `app: FastAPI` exposed and `GET /health` passes.
2. No forbidden dependency or import was added (`uvicorn`, bcrypt, `uuid4` PK).
3. All new/changed `*.py` files are `<= 350` lines.
4. ScyllaDB access goes through `cqlengine` Models + repositories; UUIDv7 PKs; Argon2id hashing; hybrid auth flows intact.
5. `unit + integration + regression` tests added/updated and `uv run pytest -q` is green.
6. SOLID review passes: thin routers, interface-injected services/repositories, no god classes.
7. Docs updated: env vars, API contract (router/schemas/OpenAPI), and table/query rationale where changed.

## 14. Documentation and Code Language

1. `AGENTS.md` (this file) is the ONLY Markdown file written in English.
2. Every other `*.md` file in this repo (`README.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `docs/*.md`) MUST be written in Vietnamese.
3. Markdown rule: code, identifiers, commands, and error codes stay in English. Only prose/explanations are in Vietnamese.
4. Backend code rule — English only: all Python code MUST be written entirely in English. This includes identifiers, docstrings, inline comments, log messages, exception messages, Pydantic descriptions, OpenAPI titles/descriptions, and test names/messages. Vietnamese is forbidden in `*.py` (including comments). API error `code` values stay in English (`EMAIL_TAKEN`); human `message` fields in API responses also stay in English — Vietnamese translation happens in the frontend.
5. A change that violates the Markdown or code language rule fails the Definition of Done.

## 15. Git, GitHub, and Docker Discipline

1. Never commit and never push to GitHub unless the user explicitly requests it (e.g. "commit", "push", "đẩy code", "tạo PR"). Finishing code is NOT permission to commit or push. No auto-commit, no auto-push, no background sync.
2. After every coding task, run `git status --short` (and `git diff --stat` when files were modified) and report the result to the user before stopping. The working tree must be left in a reviewed, intentional state.
3. Never commit junk. Junk includes: `__pycache__/`, `*.py[oc]`, `.venv/`, `dist/`, `build/`, `*.egg-info/`, `.pytest_cache/`, `.coverage`, `htmlcov/`, editor swap files, OS files (`.DS_Store`, `Thumbs.db`), and local `.env` files. When `git status` reveals an untracked junk pattern, add the pattern to `.gitignore` instead of committing the file. Never use `git add -A` blindly; stage only intentional paths.
4. Docker packaging is forbidden unless the user explicitly requests it. Forbidden without request: writing new `Dockerfile`/`compose*.yml` packaging, running `docker build`, `docker push`, `docker run`/`compose up` for packaging, and publishing images. The `Dockerfile`, `.dockerignore`, and CI docker-build gate already in this repo are the one-time explicitly requested setup — they validate with `push: false` only. Rebuilding, publishing (`push: true`), or adding new images/registries still requires a fresh explicit user request.
5. CI is defined in `.github/workflows/` as 12 required gates (see `ci.yml`: git-hygiene, file-lines, no-server, auth-crypto, english-code, docs-language, structure, unit, integration, regression, docker-build, ci-success). A PR is mergeable only when all 12 gates are green. Do not weaken gates to make a PR pass.
6. Database reset discipline: never reset the database unless the user explicitly requests it (e.g. "reset db", "reset database", "run reset_db.py"). Writing, reviewing, or verifying reset tooling is NOT permission to run it against real data: verification must use `--dry-run` (or a disposable `*_test` keyspace the user approved). A real `DROP`/recreate of a keyspace requires a fresh explicit user request every time.

## 16. Realtime: WebSocket First

Realtime features use WebSocket from day one. No polling-first, no SSE-first, no Socket.IO / Pusher / Ably / third-party realtime SaaS.

1. Transport: FastAPI `WebSocket` only. `websockets` is the single allowed extra package (FastAPI requires it for WS support). Never add Socket.IO or another realtime framework.
2. Authentication: browsers cannot set headers on the WS handshake, so auth uses a short-lived one-time ticket. Client calls `POST /ws/tickets` (authenticated REST), then opens `GET /ws?ticket=<one-time-ticket>`. Server validates the ticket (SHA-256 hash stored in ScyllaDB, single use, expires in ~60s), binds the user, and closes with `4401` on invalid/expired tickets. Never put JWT access tokens or refresh tokens in the URL. Never log tickets or tokens.
3. Channels (authorize every subscription against §8 RBAC — authentication is not authorization):
   - `notifications:{user_id}` — personal inbox live updates.
   - `attendance:{activity_id}` — live QR check-in feed for staff screens.
   - `activities:{org_id}` — org activity feed updates.
   New channels require a documented owner, query table, and tests.
4. Protocol: JSON envelopes only: `{"type": "<versioned-name>", "data": {...}}`. Server heartbeat ping every 25s; client must pong or be closed. Unknown `type` values are ignored and logged, never crash the connection. Use explicit close codes (`4401` unauthorized, `4403` forbidden, `4400` bad frame).
5. No RAM state (§12, schemas.cql §14): the connection registry is ephemeral transport only, never authoritative. Reconnect/resume always replays from ScyllaDB (scan logs, notifications, outbox rows). Fan-out coordination uses `job_leases`-style DB leases, never in-process locks. A restarted worker loses zero business facts.
6. Placement: WS route handlers live in the feature `router.py`, stay thin, and delegate to services/repositories like REST. Shared handshake/ticket/heartbeat code lives in `core/realtime.py` only.
7. Tests (§10 applies fully): handshake with valid/invalid/expired ticket, subscribe allowed vs denied, heartbeat timeout, reconnect resume from DB. Every channel ships unit + integration + regression tests.
