"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.activities.router import router as activities_router
from src.attendance.router import router as attendance_router
from src.auth.account_router import router as account_router
from src.auth.router import router as auth_router
from src.certificates.router import router as certificates_router
from src.certificates.template_router import router as certificate_template_router
from src.chat.message_router import router as chat_message_router
from src.chat.router import router as chat_router
from src.chat.ws_router import router as chat_ws_router
from src.config import get_auth_settings, get_chat_settings, get_settings
from src.database import check_connection, create_database_engine
from src.media.attach_router import router as media_attach_router
from src.media.router import router as media_router
from src.notifications.router import router as notifications_router
from src.organizations.gallery import router as organization_gallery_router
from src.organizations.router import router as organizations_router
from src.posts.comment_router import router as post_comment_router
from src.posts.feed_router import router as feed_router
from src.posts.router import router as posts_router
from src.posts.trash_router import router as post_trash_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("src")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_auth_settings()  # a missing or short JWT_SECRET stops the startup
    get_chat_settings()  # a missing or malformed CHAT_ENCRYPTION_KEY stops the startup
    engine = create_database_engine(get_settings().database_url)
    try:
        check_connection(engine)
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        engine.dispose()
        raise
    logger.info(
        "Database connected: %s", engine.url.render_as_string(hide_password=True)
    )
    app.state.engine = engine
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="AmigoACT", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> Response:
    """Leave out the rejected input, which can be a password."""
    errors = [
        {key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


app.include_router(auth_router)
app.include_router(account_router)
app.include_router(organizations_router)
app.include_router(organization_gallery_router)
app.include_router(activities_router)
app.include_router(attendance_router)
app.include_router(certificates_router)
app.include_router(certificate_template_router)
app.include_router(notifications_router)
app.include_router(media_router)
app.include_router(media_attach_router)
app.include_router(posts_router)
app.include_router(post_trash_router)
app.include_router(post_comment_router)
app.include_router(feed_router)
app.include_router(chat_router)
app.include_router(chat_message_router)
app.include_router(chat_ws_router)
