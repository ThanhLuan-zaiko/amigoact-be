"""FastAPI entrypoint. Run with: fastapi dev main.py --port 8100."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute, APIWebSocketRoute

from core.config import get_settings
from core.database import check_scylla_connection, connect
from core.exceptions import DomainError, domain_error_handler
from core.realtime import ConnectionManager

logger = logging.getLogger("amigoact")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _describe_routes(app: FastAPI) -> list[str]:
    """Return sorted 'METHOD /path' lines for every registered route."""
    lines: set[str] = set()
    for route in app.routes:
        # Included routers mount lazily; descend to their original routes.
        children = getattr(getattr(route, "original_router", None), "routes", [route])
        for child in children:
            if isinstance(child, APIRoute):
                methods = ",".join(sorted(child.methods))
                lines.add(f"{methods} {child.path}")
            elif isinstance(child, APIWebSocketRoute):
                lines.add(f"WS {child.path}")
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
    try:
        connect(
            settings.scylla_hosts_list,
            settings.scylla_keyspace,
            settings.scylla_datacenter,
        )
        from activities.seed import seed_categories
        from profiles.seed import seed_skills
        from rbac.seed import seed_rbac

        await asyncio.to_thread(seed_rbac)
        await asyncio.to_thread(seed_skills)
        await asyncio.to_thread(seed_categories)
    except Exception as exc:
        logger.error("cqlengine connection setup failed: %s", exc)
    app.state.ws_manager = ConnectionManager()
    yield
    logger.info("Shutdown complete.")


app: FastAPI = FastAPI(title="AmigoACT API", lifespan=lifespan)
app.add_exception_handler(DomainError, domain_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().frontend_urls_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from activities.detail_router import router as activity_detail_router  # noqa: E402
from activities.router import router as activities_router  # noqa: E402
from admin.router import router as admin_router  # noqa: E402
from audit.router import router as audit_router  # noqa: E402
from auth.router import router as auth_router  # noqa: E402
from certificates.router import router as certificates_router  # noqa: E402
from hours.router import router as hours_router  # noqa: E402
from notifications.router import router as notifications_router  # noqa: E402
from orgs.members_router import router as members_router  # noqa: E402
from orgs.router import router as orgs_router  # noqa: E402
from profiles.router import router as profiles_router  # noqa: E402
from realtime.router import router as realtime_router  # noqa: E402
from registrations.router import router as registrations_router  # noqa: E402
from reviews.router import router as reviews_router  # noqa: E402
from stats.router import router as stats_router  # noqa: E402

app.include_router(auth_router)
app.include_router(orgs_router)
app.include_router(members_router)
app.include_router(realtime_router)
app.include_router(admin_router)
app.include_router(notifications_router)
app.include_router(profiles_router)
app.include_router(activities_router)
app.include_router(activity_detail_router)
app.include_router(registrations_router)
app.include_router(hours_router)
app.include_router(certificates_router)
app.include_router(reviews_router)
app.include_router(stats_router)
app.include_router(audit_router)


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
