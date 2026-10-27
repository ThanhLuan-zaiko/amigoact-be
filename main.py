"""FastAPI entrypoint. Run with: fastapi dev main.py --port 8100."""

from __future__ import annotations

import asyncio

import anyio.to_thread
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.config import get_settings
from core.database import check_scylla_connection, connect
from core.exceptions import (
    DomainError,
    domain_error_handler,
    http_error_handler,
    validation_error_handler,
)
from core.guard_middleware import GuardMiddleware
from core.idempotency_middleware import IdempotencyMiddleware
from core.no_store_middleware import NoStoreErrorsMiddleware
from core.timing_middleware import TimingMiddleware
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
    # Sync endpoints run in AnyIO's pool (default 40 threads); a slow DB
    # would otherwise queue every request behind a few blocked threads.
    anyio.to_thread.current_default_thread_limiter().total_tokens = (
        settings.worker_threads
    )
    status = await asyncio.to_thread(
        check_scylla_connection,
        settings.scylla_hosts_list,
        settings.scylla_port,
        settings.scylla_keyspace,
        settings.scylla_connect_timeout_seconds,
        settings.scylla_datacenter,
        settings.scylla_username,
        settings.scylla_password,
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
            port=settings.scylla_port,
            username=settings.scylla_username,
            password=settings.scylla_password,
            connect_timeout=settings.scylla_connect_timeout_seconds,
            request_timeout=settings.scylla_request_timeout_seconds,
        )
        from activities.seed import seed_categories
        from profiles.seed import seed_skills
        from rbac.seed import seed_rbac

        await asyncio.to_thread(seed_rbac)
        await asyncio.to_thread(seed_skills)
        await asyncio.to_thread(seed_categories)
        from orgs.seed import seed_org_types

        await asyncio.to_thread(seed_org_types)
    except Exception as exc:
        logger.error("cqlengine connection setup failed: %s", exc)
    app.state.ws_manager = ConnectionManager()
    yield
    logger.info("Shutdown complete.")


app: FastAPI = FastAPI(title="AmigoACT API", lifespan=lifespan)
app.add_exception_handler(DomainError, domain_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
# Guard sits inside CORS so its rejections still carry CORS headers.
app.add_middleware(GuardMiddleware)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().frontend_urls_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Compress JSON bodies over 1 KB (feeds, directories, chat history).
app.add_middleware(GZipMiddleware, minimum_size=1024)
# 404/410 are HTTP-cacheable by default; API errors must never be.
app.add_middleware(NoStoreErrorsMiddleware)
# Outermost: measures the whole stack, including the middlewares above.
app.add_middleware(TimingMiddleware, slow_ms=get_settings().slow_request_ms)

from activities.category_router import (  # noqa: E402
    router as activity_category_router,
)
from activities.detail_router import router as activity_detail_router  # noqa: E402
from activities.browse_router import router as activity_browse_router  # noqa: E402
from activities.router import router as activities_router  # noqa: E402
from activities.slots_router import router as slots_router  # noqa: E402
from activities.tag_router import router as tag_router  # noqa: E402
from activities.user_tag_router import router as user_tag_router  # noqa: E402
from activities.media_router import router as activity_media_router  # noqa: E402
from activities.mine_router import router as my_activities_router  # noqa: E402
from orgs.structure_router import router as structure_router  # noqa: E402
from admin.router import router as admin_router  # noqa: E402
from apikeys.router import router as apikeys_router  # noqa: E402
from audit.router import router as audit_router  # noqa: E402
from auth.router import router as auth_router  # noqa: E402
from certificates.router import router as certificates_router  # noqa: E402
from chat.channels_router import router as channels_router  # noqa: E402
from chat.inbox_router import router as chat_inbox_router  # noqa: E402
from chat.media_router import router as chat_media_router  # noqa: E402
from chat.router import router as chat_router  # noqa: E402
from chat.write_router import router as chat_write_router  # noqa: E402
from hours.router import router as hours_router  # noqa: E402
from notifications.router import router as notifications_router  # noqa: E402
from orgs.members_router import router as members_router  # noqa: E402
from orgs.public_router import router as orgs_public_router  # noqa: E402
from orgs.router import router as orgs_router  # noqa: E402
from posts.comments_router import router as post_comments_router  # noqa: E402
from posts.lifecycle_router import router as post_lifecycle_router  # noqa: E402
from posts.public_router import router as posts_public_router  # noqa: E402
from posts.media_router import router as post_media_router  # noqa: E402
from posts.router import router as posts_router  # noqa: E402
from profiles.router import router as profiles_router  # noqa: E402
from rbac.router import router as rbac_router  # noqa: E402
from realtime.router import router as realtime_router  # noqa: E402
from registrations.router import router as registrations_router  # noqa: E402
from registrations.sessions_router import router as sessions_router  # noqa: E402
from registrations.appeals_router import router as appeals_router  # noqa: E402
from reports.router import router as reports_router  # noqa: E402
from reviews.router import router as reviews_router  # noqa: E402
from stats.router import router as stats_router  # noqa: E402

app.include_router(auth_router)
app.include_router(orgs_router)
app.include_router(orgs_public_router)  # after orgs: /orgs/mine beats {slug}
app.include_router(members_router)
app.include_router(structure_router)
app.include_router(apikeys_router)
app.include_router(rbac_router)
app.include_router(realtime_router)
app.include_router(admin_router)
app.include_router(notifications_router)
app.include_router(profiles_router)
app.include_router(activity_browse_router)  # before /activities/{id}
app.include_router(activities_router)
app.include_router(activity_category_router)
app.include_router(activity_detail_router)
app.include_router(slots_router)
app.include_router(tag_router)
app.include_router(user_tag_router)
app.include_router(activity_media_router)
app.include_router(my_activities_router)
app.include_router(registrations_router)
app.include_router(sessions_router)
app.include_router(appeals_router)
app.include_router(reports_router)
app.include_router(hours_router)
app.include_router(certificates_router)
app.include_router(reviews_router)
app.include_router(stats_router)
app.include_router(audit_router)
app.include_router(posts_router)
app.include_router(post_media_router)
app.include_router(post_lifecycle_router)
app.include_router(posts_public_router)  # guest announcements read
app.include_router(post_comments_router)
app.include_router(chat_router)
app.include_router(chat_inbox_router)
app.include_router(chat_media_router)
app.include_router(chat_write_router)
app.include_router(channels_router)


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
