"""Fixed-window rate limits stored in auth_rate_limits."""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.auth import AuthRateLimit


def window_start(now: datetime, window_seconds: int) -> datetime:
    seconds = int(now.timestamp())
    return datetime.fromtimestamp(seconds - seconds % window_seconds, UTC)


def seconds_until_reset(now: datetime, window_seconds: int) -> int:
    return window_seconds - int(now.timestamp()) % window_seconds


def enforce_rate_limit(
    db: Session, bucket: str, limit: int, window_seconds: int
) -> None:
    """Count one attempt and reject it over the limit.

    Commits on its own, so an attempt still counts when the request fails later.
    """
    now = datetime.now(UTC)
    start = window_start(now, window_seconds)
    upsert = (
        insert(AuthRateLimit)
        .values(bucket=bucket, window_start=start, hits=1)
        .on_conflict_do_update(
            index_elements=[AuthRateLimit.bucket, AuthRateLimit.window_start],
            set_={"hits": AuthRateLimit.hits + 1},
        )
        .returning(AuthRateLimit.hits)
    )
    hits = db.execute(upsert).scalar_one()
    db.execute(
        delete(AuthRateLimit).where(
            AuthRateLimit.bucket == bucket, AuthRateLimit.window_start < start
        )
    )
    db.commit()
    if hits > limit:
        raise api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            {"Retry-After": str(seconds_until_reset(now, window_seconds))},
        )
