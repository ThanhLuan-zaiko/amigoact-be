"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from connector.config import get_settings
from connector.database import check_connection, create_database_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("connector")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
