"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from connector.config import get_settings
from connector.database import check_connection, create_database_engine

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("connector")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_database_engine(get_settings().database_url)
    try:
        check_connection(engine)
    except Exception:
        logger.exception(
            "Database connection FAILED. Check DATABASE_URL in .env and that PostgreSQL is running."
        )
        engine.dispose()
        raise
    logger.info(
        "Database connection OK: %s", engine.url.render_as_string(hide_password=True)
    )
    app.state.engine = engine
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="AmigoACT", lifespan=lifespan)
