"""Month-bucket helpers for the chat partition walk."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID


def bucket_of(moment: datetime) -> str:
    """'YYYYMM' partition bucket of a timestamp (UTC)."""
    stamp = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).strftime("%Y%m")


def bucket_of_uuid(value: UUID) -> str:
    """Bucket of a UUIDv7 id: its leading 48 bits are unix milliseconds."""
    ms = int.from_bytes(value.bytes[:6], "big")
    return bucket_of(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))


def prev_bucket(bucket: str) -> str:
    """Previous 'YYYYMM' step."""
    year, month = int(bucket[:4]), int(bucket[4:6])
    month -= 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}{month:02d}"


def next_bucket(bucket: str) -> str:
    """Following 'YYYYMM' step."""
    year, month = int(bucket[:4]), int(bucket[4:6])
    month += 1
    if month == 13:
        year, month = year + 1, 1
    return f"{year:04d}{month:02d}"
