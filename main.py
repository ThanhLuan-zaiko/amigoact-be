"""FastAPI entrypoint. Run with: fastapi dev main.py --port 8100."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from core.config import get_settings
from core.database import check_scylla_connection

logger = logging.getLogger("amigoact")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _describe_routes(app: FastAPI) -> list[str]:
    """Return sorted 'METHOD /path' lines for every registered route."""
    lines: set[str] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            methods = ",".join(sorted(route.methods))
            lines.add(f"{methods} {route.path}")
    return sorted(lines)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: check ScyllaDB (from .env) and log routes. Never fail boot."""
    settings = get_settings()
    status = await asyncio.to_thread(
        check_scylla_connection,
        settings.scylla_hosts_list,
        settings.scylla_port,
        settings.scylla_keyspace,
        10.0,
        settings.scylla_datacenter,
    )
    app.state.db_status = {
        "ok": status.ok,
        "hosts": settings.scylla_hosts_list,
        "port": settings.scylla_port,
        "datacenter": settings.scylla_datacenter,
        "keyspace": settings.scylla_keyspace,
        "cluster_name": status.cluster_name,
        "release_version": status.release_version,
        "tables": status.tables,
        "error": status.error,
    }
    if status.ok:
        logger.info(
            "ScyllaDB connected: cluster=%s release=%s dc=%s keyspace=%s tables=%d",
            status.cluster_name,
            status.release_version,
            settings.scylla_datacenter,
            settings.scylla_keyspace,
            status.tables,
        )
    else:
        logger.error(
            "ScyllaDB unreachable at %s:%d (keyspace=%s): %s",
            ",".join(settings.scylla_hosts_list),
            settings.scylla_port,
            settings.scylla_keyspace,
            status.error,
        )
    for line in _describe_routes(app):
        logger.info("Route: %s", line)
    yield
    logger.info("Shutdown complete.")


app: FastAPI = FastAPI(title="AmigoACT API", lifespan=lifespan)


@app.get("/")
def root() -> dict[str, str]:
    """Service pointer (interactive docs live at /docs)."""
    return {"service": "amigoact-be", "docs": "/docs"}


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe: no auth, no DB dependency."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    """Readiness snapshot: result of the startup ScyllaDB check."""
    return {"status": "ok", "database": app.state.db_status}
