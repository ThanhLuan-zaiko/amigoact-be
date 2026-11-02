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
from src.config import get_auth_settings, get_settings
from src.database import check_connection, create_database_engine
from src.organizations.router import router as organizations_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("src")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_auth_settings()  # a missing or short JWT_SECRET stops the startup
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
app.include_router(activities_router)
app.include_router(attendance_router)
