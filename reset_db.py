"""Drop and recreate the dev keyspace from schemas.cql.

Reads hosts and keyspace from `.env`, touches only that one keyspace,
probes ScyllaDB reachability (native TCP, Docker, or Docker in WSL2),
then replays `schemas.cql` statement by statement.

Usage:
    uv run python reset_db.py --dry-run
    uv run python reset_db.py --yes
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import platform
import re
import shutil
import socket
import subprocess
import sys
import types

logger = logging.getLogger("reset_db")

DEFAULT_ENV = ".env"
DEFAULT_CQL = "schemas.cql"
DEFAULT_HOSTS = ("127.0.0.1",)
DEFAULT_PORT = 9042
DEFAULT_KEYSPACE = "amigoact"

KEYSPACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,47}$")
CREATE_KS_RE = re.compile(
    r"CREATE\s+KEYSPACE\s+(IF\s+NOT\s+EXISTS\s+)?(\S+)", re.IGNORECASE
)
USE_RE = re.compile(r"USE\s+(\S+)", re.IGNORECASE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset a ScyllaDB dev keyspace.")
    parser.add_argument("--env", default=DEFAULT_ENV, help="Path to .env file.")
    parser.add_argument("--cql", default=DEFAULT_CQL, help="Path to schemas.cql.")
    parser.add_argument("--hosts", default="", help="Comma-separated hosts.")
    parser.add_argument("--port", type=int, default=0, help="CQL port (0 = from env).")
    parser.add_argument("--keyspace", default="", help="Target keyspace.")
    parser.add_argument("--username", default="", help="CQL username if auth is on.")
    parser.add_argument("--password", default="", help="CQL password if auth is on.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeouts.")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation.")
    parser.add_argument("--force", action="store_true", help="Allow ENV=prod.")
    parser.add_argument("--dry-run", action="store_true", help="Parse only.")
    parser.add_argument("--no-drop", action="store_true", help="Keep existing data.")
    return parser.parse_args(argv)


def load_dotenv(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            values[key] = val
    for key in (
        "SCYLLA_HOSTS",
        "SCYLLA_PORT",
        "SCYLLA_DATACENTER",
        "SCYLLA_KEYSPACE",
        "SCYLLA_USERNAME",
        "SCYLLA_PASSWORD",
        "ENV",
    ):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def resolve_path(raw: str) -> pathlib.Path:
    direct = pathlib.Path(raw)
    if direct.is_file():
        return direct
    return pathlib.Path(__file__).with_name(pathlib.Path(raw).name)


def split_hosts(raw: str) -> list[str]:
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    return hosts or list(DEFAULT_HOSTS)


def tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_capture(cmd: list[str], timeout: float) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.strip().replace("\n", " | ")
    return text or "(no output)"


def docker_base(timeout: float) -> tuple[list[str] | None, str]:
    if shutil.which("docker"):
        return ["docker"], "Docker"
    if platform.system() == "Windows" and shutil.which("wsl"):
        probe = run_capture(["wsl", "docker", "ps"], timeout)
        if probe is not None:
            return ["wsl", "docker"], "Docker inside WSL2"
    return None, ""


def detect_scylla(hosts: list[str], port: int, timeout: float) -> str:
    probe_timeout = min(timeout, 2.0)
    reachable = [h for h in hosts if tcp_open(h, port, probe_timeout)]
    base, label = docker_base(timeout)
    container: str | None = None
    if base is not None:
        container = run_capture(
            base + ["ps", "-a", "--filter", "name=scylladb",
                    "--format", "{{.Names}} ({{.Status}})"],
            timeout,
        )
    parts: list[str] = []
    if reachable:
        targets = ", ".join(f"{h}:{port}" for h in reachable)
        parts.append(f"TCP reachable: {targets}")
    else:
        parts.append(f"TCP unreachable on port {port}")
    if container:
        parts.append(f"container via {label}: {container}")
    elif base is not None:
        parts.append(f"{label} found but no 'scylladb' container")
    else:
        parts.append("no Docker CLI found (native install or unmanaged node?)")
    if platform.system() == "Windows" and label.endswith("WSL2"):
        parts.append("hint: Windows reaches WSL2 port-forwards via 127.0.0.1")
    return "; ".join(parts)


def strip_comment(line: str) -> str:
    out: list[str] = []
    i = 0
    in_str = False
    while i < len(line):
        ch = line[i]
        nxt = line[i + 1] if i + 1 < len(line) else ""
        if ch == "'":
            if in_str and nxt == "'":
                out.append("''")
                i += 2
                continue
            in_str = not in_str
            out.append(ch)
            i += 1
            continue
        if not in_str and ((ch == "/" and nxt == "/") or (ch == "-" and nxt == "-")):
            break
        out.append(ch)
        i += 1
    return "".join(out)


def load_statements(cql_path: pathlib.Path, keyspace: str) -> tuple[list[str], str | None]:
    raw = cql_path.read_text(encoding="utf-8")
    cleaned = "\n".join(strip_comment(line) for line in raw.splitlines())
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    source: str | None = None
    statements: list[str] = []
    for chunk in cleaned.split(";"):
        stmt = chunk.strip()
        if not stmt:
            continue
        created = CREATE_KS_RE.match(stmt)
        use = USE_RE.fullmatch(stmt)
        if created:
            if source is None:
                source = created.group(2)
            start, end = created.span(2)
            stmt = stmt[:start] + keyspace + stmt[end:]
        elif use:
            if source is None:
                source = use.group(1)
            stmt = f"USE {keyspace}"
        statements.append(stmt)
    return statements, source


def confirm_drop(keyspace: str, env_name: str, auto_yes: bool, force: bool) -> bool:
    if env_name == "prod" and not force:
        logger.error("ENV=prod: refusing reset without --force.")
        return False
    if auto_yes or force:
        return True
    try:
        answer = input(
            f"Type the keyspace name '{keyspace}' to confirm DROP + "
            "recreate (anything else aborts): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer == keyspace


def count_tables(session: object, keyspace: str) -> int:
    rows = session.execute(  # type: ignore[attr-defined]
        "SELECT table_name FROM system_schema.tables WHERE keyspace_name = %s",
        [keyspace],
    )
    return sum(1 for _ in rows)


def execute_reset(
    hosts: list[str],
    port: int,
    timeout: float,
    statements: list[str],
    keyspace: str,
    username: str,
    password: str,
    datacenter: str,
    drop: bool,
) -> int:
    try:
        from cassandra.cluster import Cluster
    except ImportError:
        logger.error("cassandra-driver missing; run: uv add cassandra-driver")
        return 2
    except Exception:
        # No C extensions and no asyncore on this Python: alias asyncio reactor.
        from cassandra.io.asyncioreactor import AsyncioConnection as AsyncConn

        alias = types.ModuleType("cassandra.io.asyncorereactor")
        alias.AsyncoreConnection = AsyncConn
        sys.modules["cassandra.io.asyncorereactor"] = alias
        try:
            from cassandra.cluster import Cluster
        except Exception:
            logger.error("cassandra-driver is unusable on this Python.")
            return 2
    from cassandra.io.asyncioreactor import AsyncioConnection
    # Force asyncio reactor (Python 3.12+ removed asyncore).
    options: dict[str, object] = {
        "connect_timeout": timeout,
        "connection_class": AsyncioConnection,
        "protocol_version": 4,  # ScyllaDB max is v4; skips noisy downgrades.
    }
    if datacenter:
        from cassandra.policies import DCAwareRoundRobinPolicy
        options["load_balancing_policy"] = DCAwareRoundRobinPolicy(local_dc=datacenter)
    if username:
        from cassandra.auth import PlainTextAuthProvider

        options["auth_provider"] = PlainTextAuthProvider(username=username, password=password)
    try:
        cluster = Cluster(hosts, port=port, **options)  # type: ignore[arg-type]
        session = cluster.connect()
    except Exception as exc:
        logger.error("Cannot reach ScyllaDB at %s:%d: %s", ",".join(hosts), port, exc)
        logger.error("Try: wsl docker start scylladb (Windows) or docker start scylladb")
        return 1
    try:
        if drop:
            # Validated by KEYSPACE_RE, so interpolation is safe (no bind for names).
            session.execute(f"DROP KEYSPACE IF EXISTS {keyspace}")
            logger.info("Dropped keyspace '%s' (if it existed).", keyspace)
        total = len(statements)
        for index, stmt in enumerate(statements, 1):
            session.execute(stmt)
            if index % 20 == 0 or index == total:
                logger.info("Applied %d/%d statements.", index, total)
        tables = count_tables(session, keyspace)
        logger.info("Reset done: %d statements, %d tables in '%s'.", total, tables, keyspace)
        return 0
    except Exception as exc:
        logger.error("Reset failed: %s", exc)
        return 1
    finally:
        cluster.shutdown()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    env_path = resolve_path(args.env)
    cql_path = resolve_path(args.cql)
    if not cql_path.is_file():
        logger.error("CQL file not found: %s", cql_path)
        return 2
    config = load_dotenv(env_path)
    if env_path.is_file():
        logger.info("Loaded config from %s.", env_path)
    else:
        logger.info("No .env at %s; using flags and defaults.", env_path)
    hosts = split_hosts(args.hosts or config.get("SCYLLA_HOSTS", ""))
    port = args.port or int(config.get("SCYLLA_PORT", str(DEFAULT_PORT)))
    keyspace = args.keyspace or config.get("SCYLLA_KEYSPACE", DEFAULT_KEYSPACE)
    username = args.username or config.get("SCYLLA_USERNAME", "")
    password = args.password or config.get("SCYLLA_PASSWORD", "")
    datacenter = config.get("SCYLLA_DATACENTER", "datacenter1")
    env_name = config.get("ENV", "dev")
    if not KEYSPACE_RE.match(keyspace):
        logger.error("Invalid keyspace name: %r", keyspace)
        return 2
    logger.info("Environment: %s; target keyspace: '%s'.", env_name, keyspace)
    logger.info("ScyllaDB probe: %s.", detect_scylla(hosts, port, args.timeout))
    statements, source = load_statements(cql_path, keyspace)
    tables = sum(1 for s in statements if s[:12].upper() == "CREATE TABLE")
    logger.info(
        "Parsed %d statements (%d CREATE TABLE) from %s.",
        len(statements),
        tables,
        cql_path.name,
    )
    if source and source != keyspace:
        logger.info("Rewrote keyspace %r to %r from .env/flag.", source, keyspace)
    if args.dry_run:
        logger.info("Dry run: no database change (drop skipped).")
        return 0
    logger.info("Only keyspace '%s' will be dropped; nothing else is touched.", keyspace)
    if not confirm_drop(keyspace, env_name, args.yes, args.force):
        logger.error("Aborted by user.")
        return 3
    return execute_reset(
        hosts, port, args.timeout, statements, keyspace,
        username, password, datacenter, drop=not args.no_drop,
    )


if __name__ == "__main__":
    sys.exit(main())
